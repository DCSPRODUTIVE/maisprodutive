"""Explicit camera commands parsed locally, never from model-generated tool calls."""
import re
from live_review import normalized


def detection_command(text):
    value=normalized(text).strip().rstrip('.!?')
    if value in ('/deteccao','/deteccao status','quais cameras estao com deteccao ativa',
                 'quais cameras estao com a deteccao ativa','status da deteccao'):
        return ('status','')
    match=re.fullmatch(r'/deteccao\s+(ativar|desativar|ligar|desligar)\s+(.+)',value)
    if not match:
        match=re.fullmatch(r'(ativar|ative|ligar|ligue|habilitar|habilite|desativar|desative|desligar|desligue|desabilitar|desabilite)\s+(?:a\s+)?deteccao(?:\s+de pessoas)?\s+(?:(?:da|de|na|nas|das)\s+)?(?:camera\s+|cameras\s+)?(.+)',value)
    if match:
        return (match[1] in ('ativar','ative','ligar','ligue','habilitar','habilite'),match[2].strip())
    return None


def select_names(catalogue,selector):
    value=normalized(selector).strip()
    if value in ('todas','todas as cameras'):
        return list(catalogue)
    exact=[device for device,name in catalogue.items() if normalized(name)==value]
    matches=exact or [device for device,name in catalogue.items() if value and value in normalized(name)]
    if len(matches)!=1:
        raise ValueError('Nome não encontrado ou ambíguo. Use o nome completo. Câmeras: '+', '.join(catalogue.values())[:1200])
    return matches
