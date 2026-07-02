import streamlit as st
import requests
from PIL import Image
import io

st.title("소상공인 광고 이미지 생성기")
st.write("제품 사진과 원하는 광고 스타일을 입력하면 인스타그램 피드용 광고 이미지를 생성해드립니다.")

# 결과 이미지를 기억하는 공간
if "result_image_bytes" not in st.session_state:
    st.session_state.result_image_bytes = None

# 입력 영역
product_image = st.file_uploader("제품 사진 업로드", type=["jpg", "jpeg", "png"])
prompt = st.text_input("광고 스타일 입력 (예: 따뜻하고 감성적인 카페 분위기)")

if st.button("광고 이미지 생성"):
    if product_image is None:
        st.warning("제품 사진을 업로드해주세요.")
    elif prompt == "":
        st.warning("광고 스타일을 입력해주세요.")
    else:
        with st.spinner("광고 이미지를 생성하고 있습니다. 잠시만 기다려주세요..."):
            try:
                response = requests.post(
                    "http://localhost:8000/generate",
                    files={"product_image": product_image.getvalue()},
                    data={"prompt": prompt}
                )

                if response.status_code == 200:
                    st.session_state.result_image_bytes = response.content
                else:
                    st.error("이미지 생성에 실패했습니다. 다시 시도해주세요.")

            except requests.exceptions.ConnectionError:
                st.error("서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인해주세요.")
            except Exception as e:
                st.error(f"오류가 발생했습니다: {str(e)}")

# 결과 이미지가 있으면 항상 표시
if st.session_state.result_image_bytes is not None:
    result_image = Image.open(io.BytesIO(st.session_state.result_image_bytes))
    st.success("광고 이미지가 생성됐습니다!")
    st.image(result_image, caption="생성된 광고 이미지", use_container_width=True)
    st.download_button(
        label="광고 이미지 다운로드",
        data=st.session_state.result_image_bytes,
        file_name="ad_image.png",
        mime="image/png"
    )