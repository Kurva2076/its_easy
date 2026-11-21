import sys
from argparse import ArgumentParser, ArgumentTypeError
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen, Request

CHUNK_SIZE = 64 * 1024
"""Размер куска, равный 64 КБ"""
MB = 1_000_000
"""Мегабайт для замера скорости скачивания"""


def fetch(url: str, timeout: float) -> int:
    """
    Скачивает ответ целиком и возвращает число прочитанных байт.

    :param url: Переданный URL сайта.
    :param timeout: Заданный таймаут для ожидания ответа.
    :return: Количество прочитанных байт.
    """
    request = Request(url, headers={'User-Agent': 'download-benchmark/1.0'})
    total = 0
    with urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
    return total


def valid_url(value: str) -> str:
    """
    Проверка корректности переданного url-адреса.

    :param value: Переданный url-адрес.
    :raises: ArgumentTypeError: Url-адрес не корректен.
    :return: Проверенный url-адрес.
    """
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ArgumentTypeError(
            'Нужен полный адрес, например https://example.com/big.jpg'
        )
    return value


def main() -> int:
    """
    Измеряет скорость скачивания по-заданному URL.

    Делает N последовательных GET-запросов (по умолчанию 10) с таймаутом, равным M (по умолчанию 30 секунд),
    на каждый дожидается полного ответа, затем печатает среднее время запроса,
    общий объём данных и скорость скачивания в МБ/с.
    """
    parser = ArgumentParser(description='Замер скорости скачивания: N последовательных запросов к одному URL.')
    parser.add_argument('url', type=valid_url, help='адрес, к которому обращаться')
    parser.add_argument('-n', '--requests', type=int, default=10, help='число запросов (по умолчанию 10)')
    parser.add_argument(
        '-t',
        '--timeout',
        type=float,
        default=30.0,
        help='таймаут сетевых операций в секундах (по умолчанию 30)',
    )
    args = parser.parse_args()

    if args.requests < 1:
        parser.error('число запросов должно быть не меньше 1')

    durations = []
    total_bytes = 0

    for request_number in range(1, args.requests + 1):
        start = perf_counter()
        try:
            size = fetch(args.url, args.timeout)
        except HTTPError as e:
            print(f'Запрос {request_number}: ошибка HTTP {e.code} {e.reason}', file=sys.stderr)
            return 1
        except (URLError, TimeoutError, OSError) as e:
            print(f'Запрос {request_number}: ошибка соединения: {e}', file=sys.stderr)
            return 1
        elapsed = perf_counter() - start

        durations.append(elapsed)
        total_bytes += size
        print(f'Запрос {request_number}/{args.requests}: {size / MB:.2f} МБ за {elapsed:.3f} с')

    total_time = sum(durations)
    avg_time = total_time / len(durations)
    speed = total_bytes / MB / total_time if total_time > 0 else float('inf')

    print()
    print(f'Среднее время запроса: {avg_time:.3f} с')
    print(f'Скачано всего:         {total_bytes / MB:.2f} МБ')
    print(f'Скорость скачивания:   {speed:.2f} МБ/с')
    return 0


if __name__ == '__main__':
    sys.exit(main())
