"""Real Splash rendering regression for the red zero's completed pulse.

The archived paths remain unchanged. These checks catch the former alpha
threshold that turned glow inside the narrow zero into nearly solid red.
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
        self.splash.page.message.connect(self.events.append)
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

    def test_zero_gap_stays_open_at_every_finished_pulse_position(self):
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
        self.assertEqual(viewport['redAnimation'], 'logoGlowRed')
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
                    .filter(a => ['logoGlowRed','glowW'].includes(a.animationName))
                    .forEach(a => {{a.pause(); a.currentTime = {position};}})''')
                self.wait(75)
                image = self.splash.view.grab().toImage()
                # Original finished glow pushed the lower channel to R=245 at
                # peak. The corrected soft halo stays distinct from R=255 body.
                for point in gaps:
                    self.assertLess(pixel(image, *point), 165)
                self.assertGreater(pixel(image, 565, 130), 235)
                # Bright contour expansion must be only subpixel antialiasing.
                for y in [100, 120, 130, 150, 160]:
                    base = sum(pixel(normal, x, y) >= 200 for x in range(530, 575))
                    current = sum(pixel(image, x, y) >= 200 for x in range(530, 575))
                    self.assertLessEqual(current - base, 2)
        self.assertFalse(self.errors)
        self.evaluate('window.launcher.skip()')
        state = json.loads(self.evaluate('JSON.stringify(window.launcher.getState())'))
        self.assertEqual(state['timers'], {'pending': 0, 'intervals': 0, 'frames': 0})


if __name__ == '__main__':
    unittest.main(verbosity=2)
