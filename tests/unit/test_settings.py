import os

from swingcycle.settings import strip_pykrx_legacy_env


def test_strip_pykrx_legacy_env_removes_krx_id_pw():
    """전문가 리뷰 회귀 테스트: 운영 환경에 KRX_ID/KRX_PW가 남아있으면 pykrx가
    import 시점에 우리 로그인 조율 락과 무관하게 자체 로그인을 시도할 수 있다.
    이 함수가 실제로 그 변수를 제거하는지 직접 검증한다(모듈 import 시점 부수효과는
    다른 테스트 파일의 import 순서에 영향을 받아 검증이 어려우므로 함수를 직접 호출)."""
    os.environ["KRX_ID"] = "poison"
    os.environ["KRX_PW"] = "poison"
    try:
        strip_pykrx_legacy_env()
        assert "KRX_ID" not in os.environ
        assert "KRX_PW" not in os.environ
    finally:
        os.environ.pop("KRX_ID", None)
        os.environ.pop("KRX_PW", None)
