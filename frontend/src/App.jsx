import { useState, useEffect } from "react";

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
    fetch("http://localhost:8000/references")
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

  const handleGenerate = async () => {
    if (!productFile) {
      setError("사진을 업로드해주세요.");
      return;
    }
    if (!selectedReferenceId) {
      setError("레퍼런스를 선택해주세요.");
      return;
    }
    setError("");
    setLoading(true);
    setResultImage(null);

    try {
      const formData = new FormData();
      formData.append("product_image", productFile);
      formData.append("reference_id", selectedReferenceId);

      const response = await fetch("http://localhost:8000/generate", {
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

  const handleDownload = () => {
    const link = document.createElement("a");
    link.href = resultImage;
    link.download = "styled_image.png";
    link.click();
  };

  return (
    <div style={{ padding: "24px", fontFamily: "sans-serif", maxWidth: "900px", margin: "0 auto" }}>
      <h2>카페 음료 사진 보정 생성기 (프로토타입)</h2>
      <p style={{ color: "#666" }}>
        사진을 올리고, 원하는 분위기와 구도를 골라주세요. 별도 프롬프트 입력은 필요 없습니다.
      </p>

      {/* 1. 사진 업로드 */}
      <div style={{ marginBottom: "24px" }}>
        <h3>1. 사진 업로드</h3>
        <input type="file" accept="image/jpeg,image/png" onChange={handleFileChange} />
        {productPreviewUrl && (
          <div style={{ marginTop: "12px" }}>
            <img
              src={productPreviewUrl}
              alt="업로드한 사진 미리보기"
              style={{ maxWidth: "240px", borderRadius: "8px", border: "1px solid #ddd" }}
            />
          </div>
        )}
      </div>

      {/* 2. 레퍼런스 갤러리 */}
      <div style={{ marginBottom: "24px" }}>
        <h3>2. 분위기 · 구도 선택</h3>
        {Object.keys(groupedByMood).length === 0 && <p>레퍼런스를 불러오는 중...</p>}

        {Object.entries(groupedByMood).map(([moodId, group]) => (
          <div key={moodId} style={{ marginBottom: "20px" }}>
            <h4 style={{ marginBottom: "8px" }}>{group.mood_label}</h4>
            <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
              {group.items.map((ref) => (
                <div
                  key={ref.id}
                  onClick={() => setSelectedReferenceId(ref.id)}
                  style={{
                    cursor: "pointer",
                    border:
                      selectedReferenceId === ref.id
                        ? "3px solid #4a90e2"
                        : "1px solid #ddd",
                    borderRadius: "8px",
                    padding: "4px",
                    width: "140px",
                  }}
                >
                  <img
                    src={ref.thumbnail_url}
                    alt={ref.composition_label}
                    style={{ width: "100%", height: "120px", objectFit: "cover", borderRadius: "6px" }}
                  />
                  <div style={{ fontSize: "12px", textAlign: "center", marginTop: "4px" }}>
                    {ref.composition_label}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* 3. 생성 버튼 */}
      <button onClick={handleGenerate} disabled={loading} style={{ padding: "10px 20px" }}>
        {loading ? "생성 중..." : "이미지 생성"}
      </button>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {/* 4. 결과 */}
      {resultImage && (
        <div style={{ marginTop: "24px" }}>
          <h3>결과</h3>
          <img
            src={resultImage}
            alt="생성 결과"
            style={{ maxWidth: "400px", borderRadius: "8px", border: "1px solid #ddd" }}
          />
          <div style={{ marginTop: "12px" }}>
            <button onClick={handleDownload}>다운로드</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
