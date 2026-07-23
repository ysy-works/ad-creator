# ComfyUI AD Creator 노드 설치

이 v6 번들은 워크플로 JSON뿐 아니라 AD_* 노드 구현과 코어 Python 패키지를 포함한다.

1. 압축을 작업 저장소 루트에 푼다.
2. ComfyUI가 사용하는 Python으로 번들 루트에서 `python -m pip install -e .`를 실행한다.
3. `comfy_nodes/ad_creator` 폴더를 ComfyUI의 `custom_nodes/ad_creator`로 복사하거나 심볼릭 링크한다.
4. 환경 변수 `AD_CREATOR_ROOT`를 압축을 푼 번들 루트의 절대 경로로 지정한다.
5. ComfyUI를 재시작하고 `AD_LoadMoodPackage`, `AD_FakeGenerate`, `AD_OpenAIImageGenerate`가 검색되는지 확인한다.

`nodes.py`만 단독 복사하면 안 된다. `v3_contracts.py`, `src/ad_creator/`, 프리셋, 스키마와 설정 파일이 함께 있어야 한다.
