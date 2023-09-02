import io  # 입출력 스트림을 위한 모듈
import picamera
import logging  # 이벤트 및 메세지 기록 추적을 위한 모듈
import socketserver  # TCP서버 생성 및 관리
from threading import Condition
import threading
from http import server  # 웹 서버 제작 및 관리
import RPi.GPIO as GPIO
import time
from multiprocessing import Process, Manager  # 멀티프로세싱을 위한 모듈
import random
import functools  # partial을 쓰기 위해 불러온 모듈. partial함수는 일부 인자는 고정

# 나머지 인자는 나중에 전달할 수 있게 해줌

"""

"""
# 웹페이지
PAGE = """\
<html>
<head>
<title>RCcar Streaming</title>
<style>
    body {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100vh;
        margin: 0;
        padding: 0;
        font-family: Arial, sans-serif;
    }
    
    hl {
        margin-bottom: 20px;
    }
    
    #button-container {
        display: flex;
        gap: 10px;
        margin-top: 20px;
    }
    
    button {
        padding: 10px 20px;
        font-size: 16px;
        background-color: #66FF99;
        color: blue;
        border: none;
        cursor: pointer;
        margin: 10px;
        border-radius: 10px;
    }
    
</style>
<script>
function startCar() {
    const btnElement = document.getElementById("statusAlert"); <!-- 상태를 나타내는 요소의 id -->
    btnElement.innerText = "On...."; <!-- 요소의 내용을 On....으로 변경 -->
    var xhttp = new XMLHttpRequest(); <!-- XMLHttpRequest() 인스턴스 생성 -->
    xhttp.open("GET", "/start", true); <!-- /start를 보냄 -->
    xhttp.send();
}

function stopCar() {
    const btnElement = document.getElementById("statusAlert");
    btnElement.innerText = "Off....";
    var xhttp = new XMLHttpRequest();
    xhttp.open("GET", "/stop", true);
    xhttp.send();
}

function ctlCar(direction) {
    var xhttp = new XMLHttpRequest();
    xhttp.open("GET", "/ctlDirection" + direction, true);
    xhttp.send();
}
</script>
</head>
<body>
<h1>RCcar Streaming</h1>
<img src="stream.mjpg" width="640" height="480" />
<div id="button-container">
    <button onclick="ctlCar('forward')">GO</button>
</div>
<div id="button-container">
    <button onclick="ctlCar('left')">LEFT</button>
    <button onclick="ctlCar('stop')">STOP</button>
    <button onclick="ctlCar('right')">RIGHT</button>
</div>
<div id="button-container">
    <button onclick="ctlCar('backward')">BACK</button>
</div>
<div id="button-container">
    <h4>autonomous on/off</h4>
    <div id="statusAlert" style = "padding: 10; margin: 10">Status</div>
</div>
<div id="button-container">
    <button onclick="startCar()">Start</button>
    <button onclick="stopCar()">Stop</button>
</div>
</body>
</html>
"""

# GPIO 핀 숫자
TRIG_PIN = 23
ECHO_PIN = 24
MOTOR1_PIN1 = 17
MOTOR1_PIN2 = 27
MOTOR2_PIN1 = 6
MOTOR2_PIN2 = 5


# GPIO초기화
def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)
    GPIO.setup(MOTOR1_PIN1, GPIO.OUT)
    GPIO.setup(MOTOR1_PIN2, GPIO.OUT)
    GPIO.setup(MOTOR2_PIN1, GPIO.OUT)
    GPIO.setup(MOTOR2_PIN2, GPIO.OUT)


# 초음파센서로 거리를 구하는 함수
def get_distance():
    GPIO.output(TRIG_PIN, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, GPIO.LOW)

    while GPIO.input(ECHO_PIN) == GPIO.LOW:
        pulse_start = time.time()
    while GPIO.input(ECHO_PIN) == GPIO.HIGH:
        pulse_end = time.time()

    pulse_duration = pulse_end - pulse_start
    distance = pulse_duration * 34300 / 2

    return distance


# RC car 모터 컨트롤 함수
def control_motor(direction):
    if direction == "forward":
        GPIO.output(MOTOR1_PIN1, GPIO.HIGH)
        GPIO.output(MOTOR1_PIN2, GPIO.LOW)
        GPIO.output(MOTOR2_PIN1, GPIO.HIGH)
        GPIO.output(MOTOR2_PIN2, GPIO.LOW)
    elif direction == "backward":
        GPIO.output(MOTOR1_PIN1, GPIO.LOW)
        GPIO.output(MOTOR1_PIN2, GPIO.HIGH)
        GPIO.output(MOTOR2_PIN1, GPIO.LOW)
        GPIO.output(MOTOR2_PIN2, GPIO.HIGH)
    elif direction == "left":
        GPIO.output(MOTOR1_PIN1, GPIO.LOW)
        GPIO.output(MOTOR1_PIN2, GPIO.HIGH)
        GPIO.output(MOTOR2_PIN1, GPIO.HIGH)
        GPIO.output(MOTOR2_PIN2, GPIO.LOW)
    elif direction == "right":
        GPIO.output(MOTOR1_PIN1, GPIO.HIGH)
        GPIO.output(MOTOR1_PIN2, GPIO.LOW)
        GPIO.output(MOTOR2_PIN1, GPIO.LOW)
        GPIO.output(MOTOR2_PIN2, GPIO.HIGH)
    elif direction == "stop":
        GPIO.output(MOTOR1_PIN1, GPIO.LOW)
        GPIO.output(MOTOR1_PIN2, GPIO.LOW)
        GPIO.output(MOTOR2_PIN1, GPIO.LOW)
        GPIO.output(MOTOR2_PIN2, GPIO.LOW)


class StreamingOutput(object):  # 스트리밍 서버에서 카메라로부터 오는 프레임 데이터 처리 및 전송 클래스
    def __init__(self):
        self.frame = None
        self.buffer = io.BytesIO()
        self.condition = Condition()

    def write(self, buf):
        if buf.startswith(b"\xff\xd8"):
            # 새로운 프레임, 현재 버퍼의 내용을 복사 및 알림
            # clients는 사용할 수 있음
            self.buffer.truncate()
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
        return self.buffer.write(buf)


# 스트리밍 핸들러
class StreamingHandler(server.BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.autonomous_driving = kwargs.pop("autonomous_driving")
        super().__init__(*args, **kwargs)

    def do_GET(self):
        global output, autonomous_driving
        if self.path == "/":
            self.send_response(300)
            self.send_header("Location", "/index.html")
            self.end_headers()
        elif self.path == "/index.html":
            content = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/stream.mjpg":  # 파이카메라 프레임을 구하는 코드
            self.send_response(200)
            self.send_header("Age", 0)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header(
                "Content-Type", "multipart/x-mixed-replace; boundary=FRAME"
            )
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b"--FRAME\r\n")
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except Exception as e:
                logging.warning(
                    "Removed streaming client %s: %s", self.client_address, str(e)
                )
        elif self.path == "/start":  # 자율주행 시작
            autonomous_driving.value = True  # 공유변수를 True로 변경
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"Starting the car...")
        elif self.path == "/stop":  # 자율주행 종료
            autonomous_driving.value = False  # 공유변수를 False로 변경
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"Stopping the car...")
        # 여기부터 사용자 조작을 위한 공간
        elif self.path == "/ctlDirectionforward":
            control_motor("forward")  # GPIO모터 컨트롤 함수 실행
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"forward...")
        elif self.path == "/ctlDirectionleft":
            control_motor("left")
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"left...")
        elif self.path == "/ctlDirectionright":
            control_motor("right")
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"right...")
        elif self.path == "/ctlDirectionbackward":
            control_motor("backward")
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"backward...")
        elif self.path == "/ctlDirectionstop":
            control_motor("stop")
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"stop...")
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, autonomous_driving=None):
        self.autonomous_driving = autonomous_driving
        super().__init__(server_address, RequestHandlerClass)


def start_streaming_server(autonomous_driving):  # 인자로 공유변수를 받게 함
    global output
    with picamera.PiCamera(resolution="640x480", framerate=24) as camera:  # 파이카메라
        output = StreamingOutput()
        camera.start_recording(output, format="mjpeg")
        try:
            address = ("172.30.1.23", 8000)
            server = StreamingServer(
                address,
                functools.partial(
                    StreamingHandler, autonomous_driving=autonomous_driving
                ),
            )
            server.serve_forever()
        finally:
            camera.stop_recording()


def start_rc_control(autonomous_driving):  # 인자로 공유변수를 받게 함
    control_motor("stop")
    ctlUser = False  # 사용자모드 사용을 위한 변수(자율주행 변수가 False일 때
    # while문을 돌면서 stop motor를 한번만 실행되게 하게 함)
    while True:
        if autonomous_driving.value == True:
            ctlUser = False
            distance = get_distance()

            if distance < 50:
                if random.choice([0, 1]) == 0:
                    control_motor("left")
                else:
                    control_motor("right")
            elif distance >= 50:
                control_motor("forward")
            time.sleep(0.5)
        else:
            if ctlUser == False:
                control_motor("stop")
                ctlUser = True
            time.sleep(0.5)


# 이번 학기에 운영체제 과목을 듣고 있어 멀티 스레딩과 멀티 프로세싱에 대해 자세히 알고자
# 동영상 프레임을 구하는 부분에서는 스레드, 스트리밍과 rc카 자율주행 동작에 관해서는 멀티 프로세싱을 사용했습니다.
if __name__ == "__main__":
    with Manager() as manager:  # 공유변수를 위한 Manager함수 사용 종료시 자동으로 close되게 with ~ as구문 사용
        autonomous_driving = manager.Value("b", False)  # 자율주행 on, off를 위한 공유변수를 생성
        setup()  # GPIO 초기화
        streaming_process = Process(
            target=start_streaming_server, args=(autonomous_driving,)
        )  # 스트리밍 및 웹페이지 조작 프로세스 할당
        rc_process = Process(
            target=start_rc_control, args=(autonomous_driving,)
        )  # 자율주행 프로세스 할당
        # 멀티프로세스 할당
        streaming_process.start()
        rc_process.start()
        # 멀티프로세스 종료 대기
        streaming_process.join()
        rc_process.join()
