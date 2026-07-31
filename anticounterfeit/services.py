import re
from datetime import datetime


def parse_gs1(raw: str) -> dict:
    """Parse un code GS1 (AI 01 = GTIN, 17 = date exp, 10 = lot)"""
    result = {}
    if raw.startswith('01') and len(raw) >= 16:
        result['gtin'] = raw[2:16]
        rest = raw[16:]
        if rest.startswith('17') and len(rest) >= 8:
            result['expiry_date'] = _parse_expiry(rest[2:8])
            rest = rest[8:]
        if rest.startswith('10'):
            result['batch_number'] = rest[2:]
    return result


def _parse_expiry(yymmdd: str):
    try:
        return datetime.strptime(yymmdd, '%y%m%d').date()
    except ValueError:
        return None


def decode_medicine_from_code(raw_code: str) -> dict:
    """Décode un code scanné et vérifie son authenticité"""
    from .models import QRCode

    gs1_data = parse_gs1(raw_code)
    qr = QRCode.objects.filter(code=raw_code).select_related('medicine', 'pharmacy').first()

    if not qr:
        return {'status': 'unknown', 'gs1': gs1_data}

    if qr.status == 'revoked':
        return {'status': 'counterfeit', 'medicine': qr.medicine, 'gs1': gs1_data}

    return {'status': 'authentic', 'medicine': qr.medicine, 'pharmacy': qr.pharmacy, 'gs1': gs1_data}