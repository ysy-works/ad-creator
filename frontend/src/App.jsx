import { useState, useEffect } from "react";

/*
  디자인 토큰 (무드컷 · 카페 무드보드 소셜카드 컨셉)
  ----------------------------------------------------
  color:
    bg        #EFE8DA  (웜 오트 배경)
    surface   #FFFDF9  (카드 표면, 오프화이트)
    ink       #2B2420  (기본 텍스트, 웜 다크브라운)
    ink-soft  #6B6058  (보조 텍스트)
    accent    #8A6E4B  (로스티드 브라운 - 주 포인트, 버튼/선택 표시)
    accent-2  #5C6B4C  (세이지 그린 - 보조 포인트, 좋아요 등)
    line      #DDD2BE  (헤어라인)
  type:
    display   'Fraunces' (제목용 세리프, 절제해서 사용)
    body      'Pretendard', system-ui (한글 UI 본문)
  signature:
    카드를 실제 인스타그램이 아니라 "우리 서비스 자체 무드보드 피드"처럼
    보이게 하는 자체 아바타(커피잔 아이콘)+브랜드명("무드컷")+선택 스탬프.
    좋아요 수는 레퍼런스 id 기반으로 결정적으로 생성(매번 안 바뀜).
*/

// PC(localhost)에서 접속하든 휴대폰(같은 Wi-Fi의 IP)에서 접속하든
// 지금 브라우저 주소창의 호스트를 그대로 따라가서 API를 호출한다.
// -> IP가 바뀌어도(카페 Wi-Fi 등) 코드 수정 없이 그대로 동작함.
const API_BASE = `http://${window.location.hostname}:8000`;

const seededLikeCount = (id) => {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return 80 + (hash % 400);
};

const HeartIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M12 20.5s-7.5-4.6-10-9.4C.6 7.6 2.3 4 5.8 4c2 0 3.6 1.1 4.2 2.7C10.6 5.1 12.2 4 14.2 4c3.5 0 5.2 3.6 3.8 7.1-2.5 4.8-10 9.4-10 9.4z" />
  </svg>
);
const CommentIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M21 11.5a8.4 8.4 0 0 1-8.9 8.4 9 9 0 0 1-3.6-.7L3 20l1-4.9A8.3 8.3 0 0 1 3 11.5 8.4 8.4 0 0 1 12 3a8.6 8.6 0 0 1 9 8.5z" />
  </svg>
);
const ShareIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7" />
    <path d="M16 6l-4-4-4 4" />
    <path d="M12 2v14" />
  </svg>
);
const BookmarkIcon = ({ filled }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8">
    <path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z" />
  </svg>
);

// 인스타그램 실제 화면이 아니라, 우리 서비스만의 "무드보드 피드 카드" 프레임
function PostFrame({ children, brand = "moodcut", caption, likeCount, selected, badgeText, onClick }) {
  return (
    <div className={`post-frame${selected ? " is-selected" : ""}`} onClick={onClick}>
      <div className="post-frame__header">
        <span className="post-frame__avatar" aria-hidden="true">☕</span>
        <span className="post-frame__brand">{brand}</span>
        {selected && <span className="post-frame__stamp">{badgeText || "선택됨"}</span>}
      </div>

      <div className="post-frame__photo">{children}</div>

      <div className="post-frame__actions">
        <span className="post-frame__icon post-frame__icon--like"><HeartIcon /></span>
        <span className="post-frame__icon"><CommentIcon /></span>
        <span className="post-frame__icon"><ShareIcon /></span>
        <span className="post-frame__icon post-frame__icon--save"><BookmarkIcon /></span>
      </div>

      {(caption || likeCount) && (
        <div className="post-frame__caption">
          {likeCount != null && <strong>좋아요 {likeCount}개</strong>}
          {caption && <span> {caption}</span>}
        </div>
      )}
    </div>
  );
}

function App() {
  const [productFile, setProductFile] = useState(null);
  const [productPreviewUrl, setProductPreviewUrl] = useState(null);

  const [references, setReferences] = useState([]); // GET /references 결과 (그루핑 전 원본)
  const [selectedReferenceId, setSelectedReferenceId] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resultImage, setResultImage] = useState(null);

  // 페이지 로드 시 레퍼런스 목록 불러오기
  useEffect(() => {
    fetch(`${API_BASE}/references`)
      .then((res) => res.json())
      .then((data) => setReferences(data))
      .catch(() => setError("레퍼런스 목록을 불러오지 못했습니다."));
  }, []);

  // 업로드한 파일이 바뀌면 미리보기 URL 생성
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    setProductFile(file);
    setResultImage(null);
    if (file) {
      setProductPreviewUrl(URL.createObjectURL(file));
    } else {
      setProductPreviewUrl(null);
    }
  };

  // references 배열을 mood_id 기준으로 그루핑
  // -> 무드 개수, 무드당 구도 개수가 몇 개든 상관없이 동작함
  const groupedByMood = references.reduce((acc, ref) => {
    if (!acc[ref.mood_id]) {
      acc[ref.mood_id] = {
        mood_label: ref.mood_label,
        items: [],
      };
    }
    acc[ref.mood_id].items.push(ref);
    return acc;
  }, {});

  // 현재 선택된 레퍼런스 객체 (업로드 단계에서 안내 문구에 사용)
  const selectedReference = references.find((r) => r.id === selectedReferenceId);

  const handleGenerate = async () => {
    if (!selectedReferenceId) {
      setError("레퍼런스를 먼저 선택해주세요.");
      return;
    }
    if (!productFile) {
      setError("사진을 업로드해주세요.");
      return;
    }
    setError("");
    setLoading(true);
    setResultImage(null);

    try {
      const formData = new FormData();
      formData.append("product_image", productFile);
      formData.append("reference_id", selectedReferenceId);

      const response = await fetch(`${API_BASE}/generate`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error("이미지 생성에 실패했습니다.");
      }

      const data = await response.json();
      setResultImage(data.result_image);
    } catch (err) {
      setError(err.message || "오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  };

  // 다운로드는 프레임 없이 순수 결과 이미지(base64)만 그대로 받는다 (의도된 동작)
  const handleDownload = () => {
    const link = document.createElement("a");
    link.href = resultImage;
    link.download = "styled_image.png";
    link.click();
  };

  return (
    <div className="cafe-app">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&display=swap');

        .cafe-app {
          --bg: #EFE8DA;
          --surface: #FFFDF9;
          --ink: #2B2420;
          --ink-soft: #6B6058;
          --accent: #8A6E4B;
          --accent-2: #5C6B4C;
          --line: #DDD2BE;

          background: var(--bg);
          color: var(--ink);
          font-family: 'Pretendard', -apple-system, sans-serif;
          min-height: 100vh;
          padding: clamp(20px, 5vw, 48px);
        }

        .cafe-app__inner {
          max-width: 1400px;
          margin: 0 auto;
        }

        .cafe-app__eyebrow {
          display: inline-block;
          font-size: 12px;
          letter-spacing: 0.14em;
          color: var(--accent-2);
          font-weight: 700;
          text-align: center;
          width: 100%;
        }

        .cafe-app__title {
          font-family: 'Fraunces', serif;
          font-weight: 600;
          font-size: clamp(24px, 4vw, 36px);
          text-align: center;
          margin: 6px 0 8px;
        }

        .cafe-app__subtitle {
          text-align: center;
          color: var(--ink-soft);
          font-size: clamp(13px, 2.4vw, 15px);
          max-width: 560px;
          margin: 0 auto 40px;
          line-height: 1.6;
        }

        .section-title {
          font-family: 'Fraunces', serif;
          font-size: clamp(17px, 3vw, 20px);
          font-weight: 600;
          text-align: center;
          margin-bottom: 20px;
        }

        .mood-block { margin-bottom: 44px; }
        .mood-block__label {
          font-size: clamp(15px, 2.6vw, 17px);
          font-weight: 700;
          margin-bottom: 16px;
          color: var(--accent);
        }

        .mood-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
          gap: clamp(12px, 2.5vw, 20px);
        }

        .post-frame {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 14px;
          overflow: hidden;
          cursor: pointer;
          transition: transform 0.15s ease, box-shadow 0.15s ease;
          box-shadow: 0 1px 2px rgba(43,36,32,0.04);
        }
        .post-frame:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 20px rgba(43,36,32,0.10);
        }
        .post-frame.is-selected {
          outline: 2px solid var(--accent);
          outline-offset: 2px;
        }

        .post-frame__header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 9px 10px;
          border-bottom: 1px solid var(--line);
          position: relative;
        }
        .post-frame__avatar {
          width: 24px; height: 24px;
          border-radius: 50%;
          background: var(--bg);
          display: flex; align-items: center; justify-content: center;
          font-size: 13px;
          flex-shrink: 0;
        }
        .post-frame__brand {
          font-size: 12.5px;
          font-weight: 600;
          color: var(--ink);
        }
        .post-frame__stamp {
          margin-left: auto;
          font-size: 10.5px;
          font-weight: 700;
          color: #fff;
          background: var(--accent);
          padding: 3px 8px;
          border-radius: 999px;
          letter-spacing: 0.02em;
        }

        .post-frame__photo {
          width: 100%;
          aspect-ratio: 1 / 1;
          overflow: hidden;
          background: var(--bg);
        }
        .post-frame__photo img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          display: block;
        }

        .post-frame__actions {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 9px 10px 4px;
          color: var(--ink);
        }
        .post-frame__icon { display: flex; }
        .post-frame__icon--like { color: #B5573F; }
        .post-frame__icon--save { margin-left: auto; }

        .post-frame__caption {
          padding: 2px 10px 12px;
          font-size: 12px;
          color: var(--ink-soft);
        }
        .post-frame__caption strong {
          color: var(--ink);
          font-weight: 700;
        }

        .upload-panel {
          max-width: 420px;
          margin: 0 auto;
          text-align: center;
        }
        .upload-hint {
          font-size: 14px;
          margin-bottom: 14px;
          color: var(--ink-soft);
        }
        .upload-hint.is-active { color: var(--accent-2); font-weight: 600; }

        .file-input-wrap {
          display: inline-flex;
          align-items: center;
          gap: 10px;
        }
        .file-input-wrap input[type="file"] {
          font-size: 13px;
          color: var(--ink-soft);
        }

        .preview-thumb {
          margin-top: 16px;
        }
        .preview-thumb img {
          max-width: 220px;
          width: 100%;
          border-radius: 12px;
          border: 1px solid var(--line);
        }

        .generate-btn {
          display: block;
          margin: 32px auto 0;
          padding: 13px 40px;
          font-size: 15px;
          font-weight: 700;
          color: #fff;
          background: var(--accent);
          border: none;
          border-radius: 999px;
          cursor: pointer;
          transition: opacity 0.15s ease, transform 0.15s ease;
        }
        .generate-btn:hover:not(:disabled) { transform: translateY(-1px); }
        .generate-btn:disabled { opacity: 0.55; cursor: default; }

        .error-text {
          text-align: center;
          color: #B5573F;
          font-size: 13.5px;
          margin-top: 14px;
        }

        .result-section {
          margin-top: 48px;
          max-width: 340px;
          margin-left: auto;
          margin-right: auto;
        }
        .download-btn {
          display: block;
          margin: 14px auto 0;
          padding: 10px 26px;
          font-size: 13.5px;
          font-weight: 600;
          color: var(--accent);
          background: transparent;
          border: 1.5px solid var(--accent);
          border-radius: 999px;
          cursor: pointer;
        }
        .download-btn:hover { background: var(--accent); color: #fff; }

        @media (max-width: 480px) {
          .mood-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
        }
      `}</style>

      <div className="cafe-app__inner">
        <span className="cafe-app__eyebrow">COFFEE MOOD LAB</span>
        <h2 className="cafe-app__title">카페 음료 사진 보정 생성기</h2>
        <p className="cafe-app__subtitle">
          원하는 분위기와 구도를 먼저 고르고, 그 구도에 맞게 사진을 찍어 올려주세요.
          별도 프롬프트 입력은 필요 없습니다.
        </p>

        {/* 1. 레퍼런스 갤러리 */}
        <h3 className="section-title">1. 분위기 · 구도 선택</h3>
        {Object.keys(groupedByMood).length === 0 && (
          <p style={{ textAlign: "center", color: "var(--ink-soft)" }}>레퍼런스를 불러오는 중...</p>
        )}

        {Object.entries(groupedByMood).map(([moodId, group]) => (
          <div key={moodId} className="mood-block">
            <div className="mood-block__label">{group.mood_label}</div>
            <div className="mood-grid">
              {group.items.map((ref) => (
                <PostFrame
                  key={ref.id}
                  brand="moodcut"
                  caption={ref.composition_label}
                  likeCount={seededLikeCount(ref.id)}
                  selected={selectedReferenceId === ref.id}
                  onClick={() => setSelectedReferenceId(ref.id)}
                >
                  <img src={ref.thumbnail_url} alt={ref.composition_label} />
                </PostFrame>
              ))}
            </div>
          </div>
        ))}

        {/* 2. 사진 업로드 */}
        <h3 className="section-title" style={{ marginTop: "8px" }}>2. 사진 업로드</h3>
        <div className="upload-panel">
          {selectedReference ? (
            <p className="upload-hint is-active">
              선택한 구도: <strong>{selectedReference.mood_label} · {selectedReference.composition_label}</strong>
              {" "}— 이 구도에 맞게 촬영한 사진을 올려주세요.
            </p>
          ) : (
            <p className="upload-hint">레퍼런스를 먼저 선택해주세요.</p>
          )}
          <div className="file-input-wrap">
            <input
              type="file"
              accept="image/jpeg,image/png"
              onChange={handleFileChange}
              disabled={!selectedReferenceId}
            />
          </div>
          {productPreviewUrl && (
            <div className="preview-thumb">
              <img src={productPreviewUrl} alt="업로드한 사진 미리보기" />
            </div>
          )}
        </div>

        {/* 3. 생성 버튼 */}
        <button className="generate-btn" onClick={handleGenerate} disabled={loading}>
          {loading ? "생성 중..." : "이미지 생성"}
        </button>

        {error && <p className="error-text">{error}</p>}

        {/* 4. 결과 (다운로드는 프레임 제외, 순수 이미지만) */}
        {resultImage && (
          <div className="result-section">
            <h3 className="section-title">결과</h3>
            <PostFrame brand="moodcut" caption="방금 생성된 결과예요" likeCount={null}>
              <img src={resultImage} alt="생성 결과" />
            </PostFrame>
            <button className="download-btn" onClick={handleDownload}>다운로드</button>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
