# scripts/

Utilidades que se ejecutan de vez en cuando, no a diario: el arranque por dos
palmadas (`nexus_wake.py`, `nexus_wake.bat`, `instalar_arranque_voz.bat`,
`quitar_arranque_voz.bat`), `ABRIR_PUERTO_MOVIL.bat` (regla de cortafuegos para
llegar desde el móvil) y `revisar_antes_de_subir.py` (la auditoría de secretos
que lanza `SUBIR_A_GITHUB.bat` antes de cada subida).

Están aquí y no en la raíz porque no son la puerta de entrada diaria —eso es
`run.bat`—, pero **todos consideran la raíz del proyecto como su directorio de
trabajo** (`cd /d "%~dp0.."` en los `.bat`, `Path(__file__).parent.parent` en los
`.py`): ahí están `.venv`, `data/` y el paquete `backend`.
