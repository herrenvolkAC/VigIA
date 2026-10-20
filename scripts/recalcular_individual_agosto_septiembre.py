"""Reconstruye la evaluación individual del estudio para agosto y septiembre 2026.

Se ejecuta de forma controlada fuera de la sesión web y reemplaza los cálculos
del período, sin acumular corridas anteriores.
"""
import asyncio
import sys
from pathlib import Path

# Al ejecutarse desde scripts/, incorporar la raíz del proyecto antes de
# importar los routers de FastAPI.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routers.estudio_premios_productividad as estudio


async def _admin_local(_request):
    return {'role': 'admin', 'device_status': 'approved'}


async def main() -> None:
    estudio._admin = _admin_local
    resultado = await estudio.recalcular_individual(
        None, fecha_desde='2026-08-01', fecha_hasta='2026-09-30')
    print(resultado)


if __name__ == '__main__':
    asyncio.run(main())
