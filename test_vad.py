import os
import numpy as np
import onnxruntime as ort
import sounddevice as sd

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "silero_vad.onnx")


class SileroVAD:

    def __init__(self, model_path: str = MODEL_PATH):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Файл модели не найден: {model_path}")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(model_path, sess_options=opts)

        self.sample_rate = 16000
        # Для 16 кГц в v5 обязателен буфер контекста в 64 сэмпла
        self.context_size = 64
        self.reset_states()

    def reset_states(self):
        """Сброс скрытого состояния и буфера контекста."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.context_size), dtype=np.float32)

    def is_speech(self, audio_chunk: np.ndarray, threshold: float = 0.5):
        # 1. Приведение к float32 [-1.0, 1.0]
        if audio_chunk.dtype == np.int16:
            audio_data = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio_data = audio_chunk.astype(np.float32)

        if audio_data.ndim == 1:
            audio_data = np.expand_dims(audio_data, axis=0)

        # 2. Добавляем 64 сэмпла контекста от прошлого чанка (512 + 64 = 576)
        full_input = np.concatenate([self._context, audio_data], axis=1)

        # Сохраняем последние 64 сэмпла для следующего шага
        self._context = full_input[:, -self.context_size :]

        # 3. Инференс
        inputs = {
            "input": full_input,
            "state": self._state,
            "sr": np.array(self.sample_rate, dtype=np.int64),
        }

        outputs = self.session.run(None, inputs)

        prob = 0.0
        for item in outputs:
            if item.size > 1:
                self._state = item
            else:
                prob = float(np.squeeze(item))

        return prob >= threshold, prob


def main():
    vad = SileroVAD()
    print("\n" + "=" * 55)
    print(" ТЕСТ SILERO VAD v5")
    print(" Поговори в микрофон, отойди на диван, покликай мышкой.")
    print(" Для выхода нажми Ctrl + C")
    print("=" * 55 + "\n")

    with sd.InputStream(
        samplerate=16000, channels=1, dtype="int16", blocksize=512
    ) as stream:
        while True:
            audio_chunk, _ = stream.read(512)
            audio_flat = audio_chunk.flatten()

            max_amp = int(np.max(np.abs(audio_flat)))
            speech_detected, prob = vad.is_speech(audio_flat, threshold=0.5)

            if speech_detected:
                bar = "█" * int(prob * 20)
                print(
                    f"\r[ГОЛОС]  Вероятность: {prob:0.2f} | Сигнал: {max_amp:<5} | {bar:<20}",
                    end="",
                    flush=True,
                )
            else:
                print(
                    f"\r[ТИШИНА] Вероятность: {prob:0.2f} | Сигнал: {max_amp:<5}                     ",
                    end="",
                    flush=True,
                )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nТест завершен.")