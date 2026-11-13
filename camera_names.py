"""Human camera labels for chat; internal IDs remain server-side."""
def display_name(name,device=None):
    value=str(name or '').strip()
    if not value or (device is not None and value==str(device)) or (value.isdigit() and len(value)>5):
        return 'Câmera sem nome cadastrado'
    return value[:100]
