import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from ai_assistant import AIAssistant
from google_ai import AIError, generate
from remembered import DeviceVault
from reports import EventStore
from telegram_alerts import TelegramAlerts

KEY = 'test-google-key-'+'x'*25
BOT = '123456789:'+'B'*35


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = EventStore(self.temp.name)
        self.telegram = TelegramAlerts(self.store)
        self.telegram.send_text = MagicMock()
        self.telegram.config('owner', {'enabled':True, 'token':BOT, 'chat_id':'12345'})
        self.server = SimpleNamespace(reports=SimpleNamespace(store=self.store),
            device_vault=DeviceVault(self.temp.name), telegram=self.telegram,
            health=SimpleNamespace(snapshot={'owner':{'expected':2,'fresh':1,'stalled':['1']},
                                            'foreign':{'private':'never-send'}}), stream_snapshot=lambda:[])
        self.ai = AIAssistant(self.server, start=False)
        self.enable()

    def tearDown(self):
        self.ai.close();self.telegram.close();self.temp.cleanup()

    def enable(self, **kwargs):
        return self.ai.config('owner', {'api_key':KEY, 'enabled':True,
            'event_descriptions':True,'conversation':True,**kwargs})

    def test_encrypted_key_and_write_only_status_validation(self):
        self.assertNotIn(KEY, json.dumps(self.ai.status('owner')))
        self.assertNotIn(KEY.encode(), self.server.device_vault.path.read_bytes())
        self.assertEqual(self.ai.key('owner'), KEY)
        for values in ({'daily_limit':True},{'model':'../../evil'},{'unknown':True},{'enabled':'yes'}, {'api_key':'x\r\ny'}):
            with self.assertRaises(ValueError):self.ai.config('owner', values)
        self.ai.config('owner', {'api_key':''})
        self.assertEqual(self.ai.key('owner'), KEY)

    def test_owner_scoped_photos_and_recent_video_metadata(self):
        own = self.store.add('owner','1','Portão','person',b'own-jpeg',.9)
        foreign = self.store.add('foreign','2','Private Camera','person',b'foreign-jpeg',.9)
        self.store.video_add('foreign','2','Secret video','a'*32+'.mp4')
        with patch.object(self.ai,'preview',side_effect=lambda jpeg:jpeg):
            context, images = self.ai.context('owner')
            self.assertEqual([e['id'] for e in context['eventos_recentes']], [own])
            self.assertEqual(images[0][1], b'own-jpeg')
            self.assertNotIn('Private Camera',json.dumps(context))
            self.assertNotIn('Secret video',json.dumps(context))
            self.assertNotIn('never-send',json.dumps(context))
            self.assertEqual(self.ai.context('owner',foreign)[0]['eventos_recentes'],[])

    @patch('ai_assistant.generate',return_value='Há uma pessoa perto do portão. Foto isolada, sem sequência confirmada.')
    def test_event_is_described_without_gating_the_original_alert(self, google):
        event = self.store.add('owner','1','Portão','person',b'jpeg',.9)
        with patch.object(self.ai,'preview',return_value=b'jpeg'):
            self.ai.process('owner','event',event)
        self.assertEqual(google.call_args.args[4][0][1],b'jpeg')
        self.assertIn('Descrição por IA', self.telegram.send_text.call_args.args[1])
        with self.store.guard,self.store.connect() as db:
            self.assertIn('pessoa',db.execute('SELECT description FROM ai_events WHERE owner=? AND event=?',('owner',event)).fetchone()[0])
        self.assertIsNotNone(self.store.image('owner',event))
        self.ai.config('owner',{'enabled':False})
        self.ai.process('owner','event',event)
        self.assertEqual(google.call_count,1)

    @patch('ai_assistant.generate',return_value='Uma câmera aguarda imagens.')
    def test_chat_history_is_bounded_owner_scoped_and_status_sends_no_images(self, google):
        self.store.add('owner','1','Portão','person',b'jpeg',.9)
        self.ai.process('owner','chat','/status')
        self.assertEqual(google.call_args.args[4],[])
        self.ai.process('owner','chat','Qual câmera?')
        self.assertEqual(len(google.call_args.args[3]['conversa_anterior']),1)
        self.assertEqual(self.ai.status('owner')['used_today'],2)
        self.ai.config('owner',{'enabled':False})
        self.assertNotIn('owner',self.ai.history)

    @patch('ai_assistant.generate',return_value='Resposta')
    def test_quota_shared_by_images_and_questions_and_help_is_free(self, google):
        self.enable(daily_limit=1)
        self.ai.process('owner','chat','/ajuda')
        self.assertEqual(self.ai.status('owner')['used_today'],0)
        self.ai.process('owner','chat','/status')
        with self.assertRaisesRegex(AIError,'Limite diário'):
            self.ai.process('owner','chat','/eventos')
        self.assertEqual(google.call_count,1)

    @patch('ai_assistant.generate',side_effect=AIError('Google recusou a solicitação.'))
    def test_google_failure_does_not_retry_in_loop(self, google):
        with self.assertRaises(AIError):self.ai.process('owner','chat','/status')
        self.ai.process('owner','chat','/status')
        self.assertEqual(google.call_count,1)
        self.assertIn('espera',self.telegram.send_text.call_args.args[1])

    def test_poll_ignores_backlog_foreign_senders_groups_and_duplicate_destinations(self):
        def message(update, chat=12345, sender=12345, kind='private',text='/eventos'):
            return {'update_id':update,'message':{'date':time.time(),'chat':{'id':chat,'type':kind},
                    'from':{'id':sender,'is_bot':False},'text':text}}
        with patch.object(self.ai,'telegram_request',side_effect=[{'url':''},[message(10)]]) as api:
            self.ai.poll_once()
            self.assertEqual(api.call_args.args[2]['offset'],-1)
            self.assertTrue(self.ai.jobs.empty())
        with patch.object(self.ai,'telegram_request',return_value=[message(11,chat=999,sender=999),
                message(12,sender=999),message(13,kind='group'),message(14)]):
            self.ai.poll_once()
        self.assertEqual(self.ai.jobs.get_nowait(),('owner','chat','/eventos'))
        self.assertTrue(self.ai.jobs.empty())
        self.telegram.config('other',{'enabled':True,'token':BOT,'chat_id':'12345'})
        with self.assertRaisesRegex(ValueError,'outra conta'):
            self.ai.config('other',{'api_key':KEY,'enabled':True,'conversation':True})

    def test_existing_webhook_is_not_removed(self):
        with patch.object(self.ai,'telegram_request',return_value={'url':'https://example.test/hook'}) as api:
            self.ai.poll_once()
        self.assertEqual(api.call_count,1)
        self.assertIn('webhook',self.ai.status('owner')['message'])

    @patch('ai_assistant.generate')
    def test_detection_command_is_explicit_local_and_not_blocked_by_google_cooldown(self, google):
        self.server.set_detection=MagicMock(return_value='Detecção ativada: Portão Fundo.')
        self.ai.cooldown['owner']=time.monotonic()+300
        self.ai.process('owner','chat','Ativar detecção da câmera Portão Fundo')
        self.server.set_detection.assert_called_once_with('owner','portao fundo',True)
        self.assertIn('Portão Fundo',self.telegram.send_text.call_args.args[1]);google.assert_not_called()

    @patch('ai_assistant.generate',return_value='Cinco instantes observados.')
    def test_event_analysis_sends_five_distinct_photos_in_time_order(self, google):
        event=self.store.add('owner','839466636','Portão Fundo','person',b'best')
        self.store.save_samples('owner',event,[(100+i,b'photo-'+str(i).encode()) for i in range(5)])
        with patch.object(self.ai,'preview',side_effect=lambda image:image):self.ai.process('owner','event',event)
        images=google.call_args.args[4]
        self.assertEqual(len(images),5);self.assertEqual([img for label,img in images],[b'photo-'+str(i).encode() for i in range(5)])
        self.assertNotIn('839466636',json.dumps(google.call_args.args[3]))
        self.assertEqual(self.telegram.send_text.call_count,1)

    @patch('ai_assistant.generate')
    def test_registry_queries_are_local_and_never_injected_into_new_image_analysis(self, google):
        event=self.store.add('owner','1','Portão','person',b'jpeg')
        self.ai.process('owner','note',{'event':event,'name':'João'})
        self.ai.process('owner','chat','/cadastro João')
        self.assertIn('Portão',self.telegram.send_text.call_args.args[1])
        google.assert_not_called()
        self.assertNotIn('João',json.dumps(self.ai.context('owner',include_images=False)[0]))
        self.ai.cooldown['owner']=time.monotonic()+300
        self.ai.process('owner','chat','/cadastro')
        self.assertIn('João',self.telegram.send_text.call_args.args[1]);google.assert_not_called()

    @patch('ai_assistant.generate',return_value='Descrição dos trechos.')
    def test_live_all_is_batched_and_charged_per_three_clips(self, google):
        rows=[{'camera':str(i),'nome':f'Câmera {i}','inicio_utc':'2026-11-13T12:00:00Z','clip':b'mp4'} for i in range(7)]
        with patch.object(self.ai.live,'capture',return_value=rows) as capture:
            self.ai.process('owner','chat','/ao_vivo todas')
        self.assertEqual(capture.call_args.args[:2],('owner','todas'))
        self.assertEqual(google.call_count,3)
        self.assertTrue(all(len(call.kwargs['videos'])<=3 for call in google.call_args_list))
        self.assertEqual(self.ai.status('owner')['used_today'],3)

    def test_authenticated_reply_annotation_resolves_only_a_bound_bot_message(self):
        event=self.store.add('owner','1','Portão','person',b'jpeg')
        self.ai.notes.bind(BOT,'12345',70,'owner',event)
        with self.store.guard,self.store.connect() as db:
            db.execute('INSERT INTO ai_poll VALUES (?,?)',(self.ai.notes.bot(BOT),1))
        update={'update_id':1,'message':{'date':time.time(),'chat':{'id':12345,'type':'private'},
            'from':{'id':12345,'is_bot':False},'text':'nome: João','reply_to_message':{'message_id':70}}}
        with patch.object(self.ai,'telegram_request',return_value=[update]):self.ai.poll_once()
        self.assertTrue(self.ai.jobs.empty())
        self.assertEqual(self.store.list('owner')[0]['user_annotation'],'João')

    def test_failure_from_old_model_cannot_pause_newly_saved_configuration(self):
        def failed_old_request(*args):
            self.ai.config('owner',{'model':'gemini-flash-latest'})
            raise AIError('Falha do modelo anterior')
        with patch('ai_assistant.generate',side_effect=failed_old_request):
            self.ai.process('owner','chat','/status')
        status=self.ai.status('owner')
        self.assertEqual(status['retry_after_seconds'],0)
        self.assertFalse(status['last_failure'])
        self.assertIn('Configuração salva',status['message'])

    @patch('ai_assistant.generate',return_value='Conexão funcionando.')
    def test_explicit_diagnostic_uses_saved_settings_without_photos_or_chat_requirement(self, google):
        self.ai.config('owner',{'conversation':False,'event_descriptions':False,'model':'gemini-flash-latest'})
        self.ai.cooldown['owner']=time.monotonic()+300
        self.ai.failures['owner']='Falha anterior'
        self.ai.process('owner','test','')
        self.assertEqual(google.call_args.args[0],KEY)
        self.assertEqual(google.call_args.args[1],'gemini-flash-latest')
        self.assertEqual(google.call_args.args[4],[])
        self.assertIn('Teste concluído',self.ai.status('owner')['message'])
        self.assertEqual(self.ai.status('owner')['retry_after_seconds'],0)
        self.assertFalse(self.ai.status('owner')['last_failure'])
        self.telegram.send_text.assert_not_called()


class GeminiTests(unittest.TestCase):
    @patch('google_ai.urllib.request.build_opener')
    def test_header_secret_fixed_destination_no_tools_and_echo_redacted(self, opener):
        response=opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value=json.dumps({'candidates':[{'content':{'parts':[{'text':'Resposta '+KEY}]}}]}).encode()
        answer=generate(KEY,'gemini-2.5-flash','O que aconteceu?',{'eventos':[]},[('evento 1',b'jpeg')])
        request=opener.return_value.open.call_args.args[0]
        self.assertNotIn(KEY,request.full_url)
        self.assertEqual(request.get_header('X-goog-api-key'),KEY)
        body=json.loads(request.data)
        self.assertNotIn('tools',body)
        self.assertEqual(body['contents'][0]['parts'][2]['inline_data']['mime_type'],'image/jpeg')
        self.assertNotIn(KEY,answer)

    @patch('google_ai.urllib.request.build_opener')
    def test_error_body_and_urls_never_exposed(self, opener):
        opener.return_value.open.side_effect=urllib.error.HTTPError('https://secret/'+KEY,403,KEY,{},None)
        with self.assertRaises(AIError) as error:
            generate(KEY,'gemini-2.5-flash','pergunta',{})
        self.assertNotIn(KEY,str(error.exception))
        self.assertIn('recusou',str(error.exception))

    @patch('google_ai.urllib.request.build_opener')
    def test_live_clips_use_video_mime_and_are_bounded(self, opener):
        response=opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value=b'{"candidates":[{"content":{"parts":[{"text":"Trecho visto."}]}}]}'
        generate(KEY,'gemini-flash-latest','descreva',{},videos=[('cam',b'mp4')]*4)
        body=json.loads(opener.return_value.open.call_args.args[0].data)
        parts=body['contents'][0]['parts']
        self.assertEqual(sum(1 for p in parts if p.get('inline_data',{}).get('mime_type')=='video/mp4'),3)

    @patch('google_ai.urllib.request.build_opener')
    def test_timeout_and_missing_model_are_distinguished_and_network_wait_is_bounded(self, opener):
        from google_ai import REQUEST_TIMEOUT
        for failure,expected in ((TimeoutError(),'espera esgotado'),
            (urllib.error.URLError(TimeoutError()),'conexão com o Google esgotado'),
            (urllib.error.HTTPError('https://example.test',404,'missing',{},None),'HTTP 404')):
            opener.return_value.open.side_effect=failure
            with self.assertRaises(AIError) as error:generate(KEY,'gemini-flash-latest','teste',{})
            self.assertIn(expected,str(error.exception))
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],REQUEST_TIMEOUT)
