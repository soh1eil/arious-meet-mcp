import os
import subprocess
import sys
import uuid

import pytest

MOCK = os.path.join(os.path.dirname(__file__), "..", "..", "mock", "server.py")


@pytest.fixture(scope="session")
def mock_url():
    p = subprocess.Popen([sys.executable, MOCK, "--port", "0"], stdout=subprocess.PIPE, text=True)
    line = p.stdout.readline().strip()
    assert line.startswith("LISTENING "), line
    yield line.split(" ", 1)[1]
    p.terminate()
    p.wait(5)


@pytest.fixture
def token():
    return "test-" + uuid.uuid4().hex
