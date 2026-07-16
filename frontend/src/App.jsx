import { useState } from "react";
import Home from "./Home";
import PicmoodTool from "./PicmoodTool";

/*
  최상위 App.
  - view가 "home"이면 랜딩 페이지, "tool"이면 기존 이미지 생성 도구를 보여줌.
  - react-router 없이 상태값 하나로만 전환 (Cloudflare Pages에 별도
    SPA 라우팅 설정을 추가할 필요가 없어서 지금 규모엔 이게 더 간단함).
*/
function App() {
  const [view, setView] = useState("home");

  if (view === "tool") {
    return (
      <div>
        <button
          onClick={() => setView("home")}
          style={{
            position: "fixed",
            top: 16,
            left: 16,
            zIndex: 100,
            background: "#FFFDF9",
            border: "1px solid #DDD2BE",
            borderRadius: 999,
            padding: "8px 16px",
            fontSize: 13,
            color: "#2B2420",
            cursor: "pointer",
          }}
        >
          ← 홈으로
        </button>
        <PicmoodTool />
      </div>
    );
  }

  return <Home onStart={() => setView("tool")} />;
}

export default App;
