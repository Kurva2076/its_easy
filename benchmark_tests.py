import re
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import benchmark

SCRIPT = str(Path(__file__).with_name('benchmark.py'))
BODY_SIZE = 200_000
"""Байт в одном ответе"""
SLOW_DELAY = 0.05
"""Пауза посреди тела ответа на /slow, секунд"""


class State:
    """Счётчики, которые заполняет тестовый сервер."""

    def __init__(self):
        self.lock = threading.Lock()
        self.requests = 0
        self.active = 0
        self.max_active = 0


class StatefulServer(ThreadingHTTPServer):
    """Класс-сервер с дополнительным полем state"""

    state: State


class Handler(BaseHTTPRequestHandler):
    """Обработчик тестового сервера: /img, /slow и /missing."""

    server: StatefulServer

    def log_message(self, format, *args):
        """Плейсхолдер, чтобы не засорять вывод тестов"""
        pass

    def do_GET(self):
        """GET-запрос"""
        state = self.server.state
        with state.lock:
            state.requests += 1
            state.active += 1
            state.max_active = max(state.max_active, state.active)
        try:
            if self.path == '/missing':
                self.send_error(404)
                return
            body = b'x' * BODY_SIZE
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.path == '/slow':
                half = len(body) // 2
                self.wfile.write(body[:half])
                self.wfile.flush()
                time.sleep(SLOW_DELAY)
                self.wfile.write(body[half:])
            else:
                self.wfile.write(body)
        finally:
            with state.lock:
                state.active -= 1


def run_cli(*args):
    """Запуск изначального скрипта benchmark.py"""
    return subprocess.run(
        [sys.executable, SCRIPT, *args], capture_output=True, text=True, timeout=60
    )


class BenchmarkTests(unittest.TestCase):
    """Проверки benchmark.py на соответствие ТЗ."""

    @classmethod
    def setUpClass(cls):
        """Поднимает локальный сервер в фоновом потоке на свободном порту."""
        cls.server = StatefulServer(('127.0.0.1', 0), Handler)
        cls.server.state = State()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        """Останавливает сервер и освобождает порт."""
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        """Обнуляет счётчики сервера перед каждым тестом."""
        self.server.state = State()

    def test_fetch_reads_full_body(self):
        """fetch возвращает точный размер скачанного тела."""
        self.assertEqual(benchmark.fetch(f'{self.base}/img', 5), BODY_SIZE)

    def test_default_is_10_requests(self):
        """Без параметров делается ровно 10 запросов."""
        result = run_cli(f'{self.base}/img')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.server.state.requests, 10)

    def test_requests_are_sequential(self):
        """Запросы идут последовательно: одновременных соединений не больше одного."""
        run_cli(f'{self.base}/img')
        self.assertEqual(self.server.state.max_active, 1)

    def test_waits_for_full_response(self):
        """Скрипт дожидается конца ответа: время каждого запроса не меньше паузы сервера."""
        result = run_cli(f'{self.base}/slow')
        self.assertEqual(result.returncode, 0, result.stderr)
        times = [float(t) for t in re.findall(r'МБ за ([\d.]+) с', result.stdout)]
        self.assertEqual(len(times), 10)
        for t in times:
            self.assertGreaterEqual(t, SLOW_DELAY * 0.9)
        avg = float(re.search(r'Среднее время запроса:\s+([\d.]+) с', result.stdout).group(1))
        self.assertGreaterEqual(avg, SLOW_DELAY * 0.9)

    def test_reports_average_time_total_size_and_speed(self):
        """В выводе есть среднее время, объём и скорость, и они согласованы между собой."""
        result = run_cli(f'{self.base}/slow')
        out = result.stdout
        avg = float(re.search(r'Среднее время запроса:\s+([\d.]+) с', out).group(1))
        total = float(re.search(r'Скачано всего:\s+([\d.]+) МБ', out).group(1))
        speed = float(re.search(r'Скорость скачивания:\s+([\d.]+) МБ/с', out).group(1))

        self.assertAlmostEqual(total, 10 * BODY_SIZE / 1_000_000, places=2)
        self.assertAlmostEqual(speed, total / (10 * avg), delta=speed * 0.05)

    def test_requests_option(self):
        """Параметр -n меняет число запросов."""
        run_cli('-n', '3', f'{self.base}/img')
        self.assertEqual(self.server.state.requests, 3)

    def test_http_error_exits_with_1(self):
        """Ошибка HTTP: код выхода 1, статус в stderr, итоговой статистики нет."""
        result = run_cli(f'{self.base}/missing')
        self.assertEqual(result.returncode, 1)
        self.assertIn('404', result.stderr)
        self.assertNotIn('Скорость скачивания', result.stdout)

    def test_invalid_url_rejected(self):
        """Некорректный адрес отклоняется с кодом 2."""
        result = run_cli('not-a-url')
        self.assertEqual(result.returncode, 2)

    def test_connection_error_exits_with_1(self):
        """Недоступный сервер (порт без слушателя): код выхода 1."""
        result = run_cli('-t', '2', 'http://127.0.0.1:9/x')
        self.assertEqual(result.returncode, 1)

    def test_zero_requests_rejected(self):
        """Нулевое число запросов отклоняется с кодом 2."""
        result = run_cli('-n', '0', f'{self.base}/img')
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
