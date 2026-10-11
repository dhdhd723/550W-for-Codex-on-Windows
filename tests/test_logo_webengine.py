"""Real Splash rendering regression for the red zero's final hold and fade.

The archived paths remain unchanged. These checks catch the former alpha
threshold and blur halo that obscured the narrow zero's negative space.
"""
import json
from pathlib import Path
import sys
import time
import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launcher.app import Splash
from launcher.config import Config


class LogoRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    @staticmethod
    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def evaluate(self, code):
        loop, answer = QEventLoop(), []
        self.splash.page.runJavaScript(code, lambda value: (answer.append(value), loop.quit()))
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(5000)
        loop.exec()
        watchdog.stop()
        self.assertTrue(answer, 'JavaScript callback timed out')
        return answer[0]

    def setUp(self):
        self.splash = Splash(Config(mode='brief', sound=False))
        self.splash.resize(1280, 800)
        self.splash.move(0, 0)
        self.events, self.errors = [], []
        self.loaded_at = None
        def receive(event):
            self.events.append(event)
            if event.get('event') == 'loaded':
                self.loaded_at = time.monotonic()
        self.splash.page.message.connect(receive)
        self.splash.page.script_error.connect(self.errors.append)
        self.splash.show()
        self.splash.load()
        until = time.monotonic() + 10
        while not any(e.get('event') == 'logo_visible' for e in self.events):
            if time.monotonic() > until:
                self.fail('550W logo failed to finish drawing')
            self.wait(50)
        # Suppress native waiting furniture for consistent widget-only pixels.
        self.evaluate('window.launcher.setReady()')

    def tearDown(self):
        self.evaluate('window.launcher.finish()')
        self.wait(700)
        self.splash.close()
        self.splash.page.deleteLater()
        self.splash.view.deleteLater()
        self.splash.profile.deleteLater()
        self.splash.deleteLater()
        self.wait(50)

    def test_zero_stays_sharp_through_last_second_and_native_fade(self):
        viewport = json.loads(self.evaluate('''JSON.stringify((() => {
            const logo = document.querySelector('#logo');
            const svg = logo.closest('svg').getBoundingClientRect();
            return {x:svg.x,y:svg.y,width:svg.width,height:svg.height,
                parentFilter:getComputedStyle(logo).filter,
                redAnimation:getComputedStyle(document.querySelector('#red0')).animationName,
                redPathAnimation:getComputedStyle(document.querySelector('#red0 path')).animationName,
                whitePathAnimation:getComputedStyle(document.querySelector('#five2 path')).animationName};
        })())'''))
        self.assertEqual(viewport['parentFilter'], 'none')
        self.assertEqual(viewport['redAnimation'], 'none')
        self.assertEqual(viewport['redPathAnimation'], 'none')
        self.assertEqual(viewport['whitePathAnimation'], 'glowW')
        dpr = self.splash.view.devicePixelRatioF()

        def pixel(image, x, y):
            px = round(dpr * (viewport['x'] + x * viewport['width'] / 800))
            py = round(dpr * (viewport['y'] + y * viewport['height'] / 230))
            return image.pixelColor(px, py).red()

        # Two negative-space points: the upper opening and lower inner channel.
        gaps = [(548, 78), (550, 150)]
        self.evaluate("document.querySelector('#logo').classList.remove('finished')")
        self.wait(75)
        normal = self.splash.view.grab().toImage()
        for point in gaps:
            self.assertLessEqual(pixel(normal, *point), 25)

        self.evaluate("document.querySelector('#logo').classList.add('finished')")
        self.wait(50)
        for position in [0, 650, 1300, 1950, 2590]:
            with self.subTest(pulse_ms=position, dpr=dpr):
                self.evaluate(f'''document.querySelector('#logo').getAnimations({{subtree:true}})
                    .filter(a => a.animationName === 'glowW')
                    .forEach(a => {{a.pause(); a.currentTime = {position};}})''')
                self.wait(75)
                image = self.splash.view.grab().toImage()
                # Neither a thresholded solid bridge nor a soft blurred halo
                # may cloud the opening. The red body keeps its exact contour.
                for point in gaps:
                    self.assertLessEqual(pixel(image, *point), 10)
                self.assertGreater(pixel(image, 565, 130), 235)
                for y in [100, 120, 130, 150, 160]:
                    base = sum(pixel(normal, x, y) >= 200 for x in range(530, 575))
                    current = sum(pixel(image, x, y) >= 200 for x in range(530, 575))
                    self.assertLessEqual(current, base)

        # Also exercise wall-clock frames from the actual ~4-second brief show.
        for moment in [3300, 3700, 4000]:
            self.wait(max(1, round(moment - (time.monotonic() - self.loaded_at) * 1000)))
            with self.subTest(animation_elapsed_ms=moment, dpr=dpr):
                image = self.splash.view.grab().toImage()
                for point in gaps:
                    self.assertLessEqual(pixel(image, *point), 10)
                for y in [100, 120, 130, 150, 160]:
                    base = sum(pixel(normal, x, y) >= 200 for x in range(530, 575))
                    current = sum(pixel(image, x, y) >= 200 for x in range(530, 575))
                    self.assertLessEqual(current, base)

        self.evaluate('window.launcher.finish()')
        exit_at = time.monotonic()
        for moment in [50, 100, 150, 200, 400, 620]:
            self.wait(max(1, round(moment - (time.monotonic() - exit_at) * 1000)))
            with self.subTest(exit_elapsed_ms=moment, dpr=dpr):
                image = self.splash.view.grab().toImage()
                for point in gaps:
                    # The same CRT scanline and underlying dark page can become
                    # visible during opacity fade; compare against empty space
                    # on that row rather than requiring a literal black pixel.
                    background = pixel(image, 760, point[1])
                    self.assertLessEqual(pixel(image, *point), background + 3)
                self.assertEqual(self.evaluate("getComputedStyle(document.querySelector('#red0')).filter"), 'url("#despike")')
                self.assertEqual(self.evaluate("getComputedStyle(document.querySelector('#red0 path')).filter"), 'none')
        self.wait(75)
        self.assertTrue(any(event.get('event') == 'exit_done' for event in self.events))
        self.assertFalse(self.errors)
        state = json.loads(self.evaluate('JSON.stringify(window.launcher.getState())'))
        self.assertEqual(state['timers'], {'pending': 0, 'intervals': 0, 'frames': 0})


if __name__ == '__main__':
    unittest.main(verbosity=2)
