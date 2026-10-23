"""Бережём процессор и память: настройки onnxruntime для всех нейросетей программы (Piper, ruaccent, GLaDOS)
и пониженный приоритет процесса.

По умолчанию onnxruntime на каждую фразу берёт все ядра и между фразами крутит потоки вхолостую —
отсюда скачки до 50% CPU, когда чат часто пользуется TTS. С 3 потоками (замер на i7-10750H): ~20% вместо ~50%,
речь всё равно считается в 2+ раза быстрее, чем звучит. Вызывать до первой загрузки модели.
"""
import os

BELOW_NORMAL_PRIORITY_CLASS = 0x4000
_applied = False


def apply(threads=3, low_priority=True):
    global _applied
    if _applied:
        return
    _applied = True
    threads = int(threads or 0)
    if low_priority and os.name == "nt":
        try:   # игра и OBS получают процессор первыми; дочерний движок GLaDOS наследует приоритет
            import ctypes
            k = ctypes.windll.kernel32
            k.GetCurrentProcess.restype = ctypes.c_void_p
            k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass
    if threads <= 0:   # 0 — как было: onnxruntime решает сам
        return
    try:
        import onnxruntime as ort
    except Exception:
        return
    orig = ort.InferenceSession
    if getattr(orig, "_tts_tuned", False):
        return

    class TunedSession(orig):
        _tts_tuned = True

        def __init__(self, path_or_bytes, sess_options=None, *args, **kwargs):
            so = sess_options if sess_options is not None else ort.SessionOptions()
            so.intra_op_num_threads = threads
            so.inter_op_num_threads = 1
            so.enable_cpu_mem_arena = False   # память после длинной фразы возвращается, а не держится «про запас»
            try:
                so.add_session_config_entry("session.intra_op.allow_spinning", "0")   # не крутить потоки вхолостую
            except Exception:
                pass
            super().__init__(path_or_bytes, so, *args, **kwargs)

    ort.InferenceSession = TunedSession   # ruaccent/Piper/TeraTTS берут класс отсюда при первой загрузке


def apply_from_env():
    """Для воркера GLaDOS: настройки приходят через переменные окружения."""
    apply(os.environ.get("TTS_CPU_THREADS", "3"), os.environ.get("TTS_LOW_PRIORITY", "1") != "0")
