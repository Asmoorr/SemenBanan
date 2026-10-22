import io
import unittest
import wave

from piano import ASSETS, local_composer, render_piano, score_notes


def score():
    return {"tempo": 100,
            "melody": [{"midi": n, "beats": 1} for n in
                       [64, 67, 69, 67, 65, 69, 72, 69, 64, 67, 71, 67, 62, 65, 67, 60]],
            "chords": [[48, 52, 55], [53, 57, 60], [48, 52, 55], [43, 47, 50]]}


class Piano(unittest.TestCase):
    @unittest.skipUnless((ASSETS / "TimGM6mb.sf2").exists(), "Run setup_music.py for audio integration tests")
    def test_soundfont_renders_non_silent_audio(self):
        audio, duration = render_piano(score_notes(score()), 100)
        with wave.open(io.BytesIO(audio)) as wav:
            self.assertEqual(wav.getframerate(), 24000)
            self.assertGreater(len(set(wav.readframes(wav.getnframes()))), 100)
        self.assertGreaterEqual(duration, 9)
        self.assertLess(duration, 20)

    @unittest.skipUnless((ASSETS / "nanomaestro/model.onnx").exists(), "Run setup_music.py for model integration tests")
    def test_local_model_generates_beyond_primer_with_bounded_notes(self):
        notes = local_composer().compose(score(), seed=42)
        self.assertTrue(any(n["start"] >= 12 for n in notes))
        self.assertTrue(all(21 <= n["midi"] <= 108 for n in notes))
        self.assertTrue(all(0 <= n["start"] < 16 and 0 < n["beats"] <= 4 for n in notes))


if __name__ == "__main__":
    unittest.main()
