import unittest

from preview import decode_bytes, looks_like_text, should_preview_as_text


class PreviewTests(unittest.TestCase):
    def test_utf8_decode(self):
        decoded = decode_bytes("hello π".encode("utf-8"))
        self.assertEqual(decoded.encoding, "utf-8")
        self.assertIn("π", decoded.text)

    def test_utf16_decode(self):
        decoded = decode_bytes("hello".encode("utf-16"))
        self.assertEqual(decoded.encoding, "utf-16")
        self.assertEqual(decoded.text, "hello")

    def test_latin1_fallback(self):
        decoded = decode_bytes(b"\xff")
        self.assertEqual(decoded.encoding, "latin-1")

    def test_looks_like_text(self):
        self.assertTrue(looks_like_text(b"abc 123\nxyz"))
        self.assertFalse(looks_like_text(bytes([0, 159, 255, 13, 0, 0, 1, 2])))

    def test_text_extension_forces_text(self):
        self.assertTrue(should_preview_as_text(".dat", bytes([0, 1, 2, 3])))


if __name__ == "__main__":
    unittest.main()
