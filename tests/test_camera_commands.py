import unittest
from camera_commands import detection_command,select_names


class CameraCommandTests(unittest.TestCase):
    def test_explicit_portuguese_commands_and_names(self):
        for text,expected in [('Ativar detecção da câmera Portão Fundo',(True,'portao fundo')),
            ('Desative a detecção de pessoas da câmera Frente 1',(False,'frente 1')),
            ('/deteccao desativar Frente 2',(False,'frente 2')),
            ('Quais câmeras estão com detecção ativa?',('status',''))]:
            self.assertEqual(detection_command(text),expected)
        self.assertIsNone(detection_command('Não ativar detecção da câmera Frente 1'))
        self.assertIsNone(detection_command('O que aconteceu na câmera Frente 1?'))
        catalogue={'secret-1':'Frente 1','secret-2':'Frente 2','secret-3':'Portão Fundo'}
        self.assertEqual(select_names(catalogue,'portao fundo'),['secret-3'])
        with self.assertRaises(ValueError):select_names(catalogue,'frente')
        with self.assertRaises(ValueError):select_names(catalogue,'secret-3')
