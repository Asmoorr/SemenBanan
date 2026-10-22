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
    @unittest.skipUnless((ASSETS / "GeneralUser-GS.sf2").exists(), "Run setup_music.py for audio integration tests")
    def test_soundfont_renders_non_silent_audio(self):
        audio, duration = render_piano(score_notes(score()), 100)
        with wave.open(io.BytesIO(audio)) as wav:
            self.assertEqual(wav.getframerate(), 48000)
            self.assertEqual(wav.getnchannels(), 2)
            self.assertGreater(len(set(wav.readframes(wav.getnframes()))), 100)
        self.assertGreaterEqual(duration, 9)
        self.assertLess(duration, 20)

    @unittest.skipUnless((ASSETS / "nanomaestro/model.onnx").exists(), "Run setup_music.py for model integration tests")
    def test_local_model_generates_beyond_primer_with_bounded_notes(self):
        notes = local_composer().compose(score(), seed=42)
        self.assertTrue(any(n["start"] >= 12 for n in notes))
        self.assertTrue(all(21 <= n["midi"] <= 108 for n in notes))
        self.assertTrue(all(0 <= n["start"] < 16 and 0 < n["beats"] <= 4 for n in notes))

    @unittest.skipUnless((ASSETS / "nanomaestro/model.onnx").exists(), "Run setup_music.py for model integration tests")
    def test_sixteen_bars_are_generated_and_rendered(self):
        notes = local_composer().compose(score(), seed=42, bars=16)
        self.assertTrue(any(n["start"] >= 60 for n in notes))
        self.assertTrue(all(0 <= n["start"] < 64 and n["start"] + n["beats"] <= 64 for n in notes))
        audio, duration = render_piano(notes, 110)
        self.assertGreaterEqual(duration, 34)
        self.assertLess(duration, 45)


if __name__ == "__main__":
    unittest.main()
