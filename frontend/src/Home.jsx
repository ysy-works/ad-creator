import { useState, useEffect } from "react";

/*
  Picmood 홈 화면.
  - 히어로(첫 화면)만 화면 높이를 꽉 채우고(min-height:100vh), 나머지 섹션은
    내용만큼만 차지함 (전 버전에서 전 섹션을 100vh로 했더니 마지막 CTA
    버튼이 flex stretch 때문에 가로로 쭉 늘어나는 버그가 있었음 -> 이번에
    히어로 외 섹션은 flex 자체를 안 쓰는 구조로 되돌려서 근본적으로 해결).
  - 우측 상단 KO/EN 클릭하면 페이지 전체 문구가 실제로 번역됨.
    무드/구도 이름(뉴트럴 화이트, 클로즈업 등)은 references.json에 없는
    영문 표기라, id 기준 매핑 테이블을 따로 둬서 처리함.
*/

const MOOD_LABEL = {
  ko: { natural_white: "뉴트럴 화이트", wood: "우드", vivid: "Vivid" },
  en: { natural_white: "Neutral White", wood: "Wood", vivid: "Vivid" },
};
const COMPOSITION_LABEL = {
  ko: {
    product_large: "클로즈업",
    product_center: "미디움샷",
    aerial_shot: "항공샷",
    handheld_lifestyle: "손에 들고 있는 샷",
  },
  en: {
    product_large: "Close-up",
    product_center: "Medium shot",
    aerial_shot: "Aerial shot",
    handheld_lifestyle: "Handheld",
  },
};
const COMPOSITION_CAPTION = {
  ko: {
    product_large: "가까이서 담은 진한 한 잔",
    product_center: "테이블 위, 자연스러운 순간",
    aerial_shot: "위에서 내려다본 오늘의 한 컷",
    handheld_lifestyle: "손끝에 걸린 편안한 하루",
  },
  en: {
    product_large: "A rich cup, up close",
    product_center: "A natural moment on the table",
    aerial_shot: "Today's shot from above",
    handheld_lifestyle: "A cozy moment in hand",
  },
};

const STR = {
  ko: {
    navProcess: "이용 방법",
    navGallery: "스타일 보기",
    navFaq: "자주 묻는 질문",
    start: "시작하기",
    eyebrow: "COFFEE MOOD LAB",
    heroTitle1: "내가 찍은 사진으로",
    heroTitleSpan: "인스타 무드컷",
    heroTitle2: " 만들기",
    heroSubtitle: "사진 한 장만 올리면 어울리는 분위기로 보정하고, 바로 올릴 캡션까지 만들어드려요.",
    exploreStyles: "스타일 둘러보기",
    stat1Num: "12", stat1Label: "무드 × 구도 조합",
    stat2Num: "3", stat2Label: "단계로 끝",
    stat3Num: "1장", stat3Label: "만 있으면 시작",
    processKicker: "이용 방법",
    processTitle1: "사진 올리고, 스타일 고르고,",
    processTitle2: "기다리기만 하면 돼요",
    processSub: "어려운 편집 프로그램도, 촬영 장비도 필요 없어요.",
    step1Title: "사진 업로드",
    step1Desc: "휴대폰으로 편하게 찍은 음료 사진이면 충분해요.",
    step2Title: "스타일 선택",
    step2Desc: "뉴트럴 화이트, 우드, Vivid 중 원하는 무드와 구도를 골라요.",
    step3Title: "결과 확인",
    step3Desc: "완성된 사진과 캡션까지 바로 받아 게시하면 끝.",
    baKicker: "비포 앤 애프터",
    baTitle: "같은 사진, 완전히 다른 무드",
    baSub: "촬영을 다시 하지 않아도, 이미 찍어둔 사진으로 충분해요.",
    baBefore: "촬영 그대로",
    baAfter: "완성된 한 컷",
    galleryKicker: "스타일 보기",
    galleryTitle: "12가지 무드 × 구도",
    gallerySub: "사진을 눌러보면 어떤 무드·구도인지 볼 수 있어요.",
    faqKicker: "자주 묻는 질문",
    faqTitle: "궁금한 점이 있다면",
    faqItems: [
      { q: "어떤 사진을 올려도 되나요?", a: "휴대폰으로 찍은 음료 사진이면 충분해요. 별도의 촬영 장비나 조명은 필요 없어요." },
      { q: "생성에 시간이 얼마나 걸리나요?", a: "보통 3~5분 정도 걸려요." },
      { q: "결과 이미지를 상업적으로 써도 되나요?", a: "네, 인스타그램 게시물이나 매장 홍보용으로 자유롭게 사용하실 수 있어요." },
      { q: "캡션도 같이 만들어주나요?", a: "이미지 생성 후 메뉴명과 게시 목적을 입력하면, 캡션과 해시태그까지 함께 만들어드려요." },
    ],
    finalTitle1: "다음 게시물,",
    finalTitle2Pre: "이번엔 ",
    finalTitle2Post: "로",
    footerNote: "코드잇 8기 팀 프로젝트 · Coffee Mood Lab",
  },
  en: {
    navProcess: "How it works",
    navGallery: "Gallery",
    navFaq: "FAQ",
    start: "Get started",
    eyebrow: "COFFEE MOOD LAB",
    heroTitle1: "Turn your own photo into",
    heroTitleSpan: "an Instagram mood shot",
    heroTitle2: "",
    heroSubtitle: "Upload one photo and we'll style it to match your mood, captions included.",
    exploreStyles: "Browse styles",
    stat1Num: "12", stat1Label: "mood × angle combos",
    stat2Num: "3", stat2Label: "steps, done",
    stat3Num: "1", stat3Label: "photo is all you need",
    processKicker: "How it works",
    processTitle1: "Upload, pick a style,",
    processTitle2: "and wait",
    processSub: "No editing skills or camera gear needed.",
    step1Title: "Upload a photo",
    step1Desc: "A casual phone shot of your drink is enough.",
    step2Title: "Pick a style",
    step2Desc: "Choose a mood and angle from Neutral White, Wood, or Vivid.",
    step3Title: "See the result",
    step3Desc: "Get your finished photo and caption, ready to post.",
    baKicker: "Before & after",
    baTitle: "Same photo, a whole new mood",
    baSub: "No reshoot needed — the photo you already have is enough.",
    baBefore: "As shot",
    baAfter: "Picmood result",
    galleryKicker: "Gallery",
    galleryTitle: "12 moods × angles",
    gallerySub: "Tap a photo to see its mood and angle.",
    faqKicker: "FAQ",
    faqTitle: "Got questions?",
    faqItems: [
      { q: "What kind of photo can I upload?", a: "A phone photo of your drink is enough. No special equipment or lighting needed." },
      { q: "How long does it take?", a: "It usually takes 3–5 minutes." },
      { q: "Can I use the results commercially?", a: "Yes, feel free to use them for Instagram posts or store promotions." },
      { q: "Do you generate captions too?", a: "After the image is ready, add a menu name and purpose and we'll write a caption and hashtags." },
    ],
    finalTitle1: "Your next post,",
    finalTitle2Pre: "made with ",
    finalTitle2Post: "",
    footerNote: "A Codeit cohort 8 team project · Coffee Mood Lab",
  },
};

function FaqItem({ q, a, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className={`faq-item${open ? " is-open" : ""}`}>
      <button className="faq-q" onClick={() => setOpen((v) => !v)}>
        <span>{q}</span>
        <span className="faq-chev">▾</span>
      </button>
      {open && <p className="faq-a">{a}</p>}
    </div>
  );
}

// PicmoodTool의 PostFrame과 동일한 규칙으로 시드 기반 좋아요 수 생성 (매번 안 바뀜)
const seededLikeCount = (id) => {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return 80 + (hash % 400);
};

const MiniHeartIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 20.5s-7.5-4.6-10-9.4C.6 7.6 2.3 4 5.8 4c2 0 3.6 1.1 4.2 2.7C10.6 5.1 12.2 4 14.2 4c3.5 0 5.2 3.6 3.8 7.1-2.5 4.8-10 9.4-10 9.4z" />
  </svg>
);
const MiniCommentIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 11.5a8.4 8.4 0 0 1-8.9 8.4 9 9 0 0 1-3.6-.7L3 20l1-4.9A8.3 8.3 0 0 1 3 11.5 8.4 8.4 0 0 1 12 3a8.6 8.6 0 0 1 9 8.5z" />
  </svg>
);
const MiniShareIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7" />
    <path d="M16 6l-4-4-4 4" />
    <path d="M12 2v14" />
  </svg>
);
const MiniBookmarkIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z" />
  </svg>
);

function Home({ onStart, lang = "ko", setLang }) {
  const [references, setReferences] = useState([]);
  const [activeCardId, setActiveCardId] = useState(null);
  const t = STR[lang];

  useEffect(() => {
    fetch("/references.json")
      .then((res) => res.json())
      .then((data) => setReferences(data))
      .catch(() => {});
  }, []);

  // 히어로에 보여줄 카드는 무드마다 하나씩, 구도까지 지정해서 고정 선택
  // (뉴트럴화이트-클로즈업, 우드-미디움샷, Vivid-손에든샷)
  const HERO_PICKS = [
    { mood: "natural_white", comp: "product_large" },
    { mood: "wood", comp: "product_center" },
    { mood: "vivid", comp: "handheld_lifestyle" },
  ];
  const heroCards = HERO_PICKS
    .map((p) => references.find((r) => r.mood_id === p.mood && r.composition_id === p.comp))
    .filter(Boolean);

  // 레퍼런스 카드 정렬: 뉴트럴화이트→우드→Vivid, 각 무드 안에서는
  // 클로즈업→미디움샷→항공샷→손에든샷 순서로 고정. JSON 안의 원래 순서와
  // 무관하게 항상 이 순서로 보이게 함.
  const MOOD_ORDER = ["natural_white", "wood", "vivid"];
  const COMPOSITION_ORDER = ["product_large", "product_center", "aerial_shot", "handheld_lifestyle"];
  const galleryItems = [...references].sort((a, b) => {
    const moodDiff = MOOD_ORDER.indexOf(a.mood_id) - MOOD_ORDER.indexOf(b.mood_id);
    if (moodDiff !== 0) return moodDiff;
    return COMPOSITION_ORDER.indexOf(a.composition_id) - COMPOSITION_ORDER.indexOf(b.composition_id);
  });

  const toggleCard = (id) => {
    setActiveCardId((cur) => (cur === id ? null : id));
  };

  const moodLabel = (ref) => MOOD_LABEL[lang][ref.mood_id] || ref.mood_label;
  const compLabel = (ref) => COMPOSITION_LABEL[lang][ref.composition_id] || ref.composition_label;
  const compCaption = (ref) => COMPOSITION_CAPTION[lang][ref.composition_id] || compLabel(ref);

  return (
    <div className="home">
      <style>{`
        html, body {
          display: block;
          margin: 0;
          padding: 0;
          width: 100%;
        }
        #root {
          width: 100%;
        }
        *, *::before, *::after {
          box-sizing: border-box;
        }
        :root {
          --bg: #EFE8DA;
          --surface: #FFFDF9;
          --ink: #2B2420;
          --ink-soft: #554A40;
          --accent: #8A6E4B;
          --accent-2: #5C6B4C;
          --line: #DDD2BE;
        }
        .home { font-family: 'Pretendard', system-ui, sans-serif; color: var(--ink); background: var(--bg); }
        .home img { max-width: 100%; display: block; }
        .home button { font-family: inherit; cursor: pointer; border: none; }
        .home .wrap { max-width: 1180px; margin: 0 auto; padding: 0 32px; }

        .home-header {
          position: sticky; top: 0; z-index: 50;
          background: rgba(43,36,32,0.94); backdrop-filter: blur(8px);
        }
        .home-nav {
          display: flex; align-items: center; justify-content: space-between;
          padding: 20px 32px; max-width: 1180px; margin: 0 auto;
        }
        .home-logo { font-family: 'Fraunces', serif; font-size: 22px; color: var(--surface); }
        .home-nav-mid { display: flex; gap: 32px; font-size: 15px; color: #E4DCCC; }
        .home-nav-mid a { color: inherit; text-decoration: none; }
        .home-nav-right { display: flex; align-items: center; gap: 18px; }
        .home-lang { font-size: 13px; color: #C9BFAE; background: none; display: flex; gap: 4px; }
        .home-lang button { background: none; color: #8F8474; font-size: 13px; font-weight: 700; padding: 2px; }
        .home-lang button.is-active { color: var(--surface); text-decoration: underline; text-underline-offset: 3px; }
        .home-btn-primary {
          background: var(--accent); color: #fff; padding: 10px 22px;
          border-radius: 999px; font-size: 14px; font-weight: 700;
          border: 1.5px solid var(--accent);
        }
        .home-btn-primary:hover { opacity: 0.92; }
        .home-link-text {
          background: none; color: var(--surface); font-size: 15px; font-weight: 600;
          text-decoration: underline; text-underline-offset: 4px; padding: 4px 2px;
        }

        .home-hero {
          position: relative; background: var(--bg); color: var(--ink);
          padding: 130px 32px 90px; overflow: hidden; text-align: center;
          min-height: 100vh; display: flex; flex-direction: column; justify-content: center; box-sizing: border-box;
        }
        .home-hero-inner {
          max-width: 900px; margin: 0 auto; position: relative; z-index: 2;
        }
        .home-eyebrow { font-size: 13px; letter-spacing: 3px; color: var(--accent-2); font-weight: 700; margin-bottom: 22px; }
        .home-hero h1 { font-family: 'Fraunces', serif; font-weight: 600; font-size: clamp(38px, 5.4vw, 58px); line-height: 1.3; margin-bottom: 26px; color: var(--ink); }
        .home-hero h1 span { color: var(--accent); }
        .home-hero p { font-size: 18px; color: var(--ink-soft); max-width: 480px; margin: 0 auto 40px; line-height: 1.7; }
        .home-hero-cta { display: flex; gap: 16px; align-items: center; justify-content: center; margin-bottom: 56px; }
        .home-btn-large { padding: 15px 30px; font-size: 16px; width: 210px; text-align: center; white-space: nowrap; box-sizing: border-box; }
        .home-btn-secondary {
          background: transparent; border: 1.5px solid var(--ink); color: var(--ink);
          padding: 15px 30px; border-radius: 999px; font-size: 16px; font-weight: 700;
        }
        .home-btn-secondary:hover { background: rgba(43,36,32,0.06); }
        .home-stat-row { display: flex; gap: 40px; justify-content: center; font-size: 15px; color: var(--ink-soft); }
        .home-stat-row b { color: var(--ink); font-family: 'Fraunces', serif; font-size: 20px; display: block; margin-bottom: 2px; }

        .home-float-card {
          position: absolute; width: 270px; border-radius: 16px; overflow: hidden;
          box-shadow: 0 24px 50px rgba(0,0,0,0.22); background: var(--surface);
        }
        .fc-header { display: flex; align-items: center; gap: 8px; padding: 12px 13px; border-bottom: 1px solid var(--line); }
        .fc-avatar {
          width: 26px; height: 26px; border-radius: 50%; background: var(--bg);
          display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0;
        }
        .fc-brand { font-size: 14px; font-weight: 700; color: var(--ink); }
        .home-float-card .fc-photo { width: 100%; aspect-ratio: 1 / 1; object-fit: cover; display: block; }
        .fc-actions { display: flex; align-items: center; gap: 12px; padding: 11px 13px 4px; color: var(--ink); }
        .fc-actions svg { width: 18px; height: 18px; }
        .fc-actions svg:last-child { margin-left: auto; }
        .home-float-card .fc-cap { padding: 6px 13px 13px; font-size: 14.5px; color: var(--ink-soft); line-height: 1.45; }
        .home-float-card .fc-cap b { color: var(--ink); font-weight: 700; }
        .fc1 { top: 9%; left: 9%; transform: rotate(-7deg); }
        .fc2 { top: 7%; right: 10%; transform: rotate(8deg); }
        .fc3 { bottom: 10%; left: 18%; transform: rotate(5deg); width: 226px; }

        .home-section { padding: 144px 32px; }
        .home-section-head { text-align: center; max-width: 560px; margin: 0 auto 56px; }
        .home-kicker { font-size: 13px; letter-spacing: 2.5px; color: var(--accent-2); font-weight: 700; margin-bottom: 14px; }
        .home-section-head h2 { font-family: 'Fraunces', serif; font-weight: 600; font-size: 34px; line-height: 1.4; margin-bottom: 16px; color: var(--ink); }
        .home-section-head p { font-size: 16px; color: var(--ink-soft); line-height: 1.7; }

        .home-steps { display: grid; grid-template-columns: repeat(3,1fr); gap: 24px; max-width: 1180px; margin: 0 auto; }
        .home-step { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 30px 26px; display: flex; flex-direction: column; }
        .home-step-num { font-family: 'Fraunces', serif; font-size: 14px; color: var(--accent); margin-bottom: 16px; }
        .home-step h3 { font-size: 18px; margin-bottom: 8px; color: var(--ink); }
        .home-step p { font-size: 15px; color: var(--ink-soft); line-height: 1.65; margin-bottom: 18px; }
        .home-step-visual { height: 130px; border-radius: 10px; background: var(--ink); display: flex; align-items: center; justify-content: center; margin-top: auto; }

        .home-ba { background: var(--accent-2); color: var(--surface); }
        .home-ba .home-kicker { color: #E3EAD5; }
        .home-ba .home-section-head p { color: #E3EAD5; }
        .home-ba-grid { display: grid; grid-template-columns: 1fr 1fr; max-width: 760px; margin: 0 auto; border-radius: 16px; overflow: hidden; box-shadow: 0 24px 56px rgba(0,0,0,0.28); }
        .home-ba-col { position: relative; aspect-ratio: 4/5; display: flex; align-items: center; justify-content: center; }
        .home-ba-col.before { background: #46503C; }
        .home-ba-col.after img { width: 100%; height: 100%; object-fit: cover; }
        .home-ba-tag { position: absolute; top: 14px; left: 14px; font-size: 12px; padding: 5px 13px; border-radius: 999px; font-weight: 700; }
        .home-ba-col.before .home-ba-tag { background: rgba(255,255,255,0.18); color: #F5F2EA; }
        .home-ba-col.after .home-ba-tag { background: var(--accent); color: #fff; z-index: 2; }

        .home-gallery { max-width: 1180px; margin: 0 auto; display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
        .home-g-card {
          border-radius: 12px; overflow: hidden;
          position: relative; background: var(--surface); border: 1px solid var(--line);
          cursor: pointer; aspect-ratio: 3 / 4;
        }
        .home-g-card img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.35s ease; }
        .home-g-card:hover img { transform: scale(1.06); }
        .home-g-overlay {
          position: absolute; inset: 0; background: rgba(43,36,32,0.72);
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          text-align: center; padding: 16px; opacity: 0; transition: opacity 0.2s ease;
          pointer-events: none;
        }
        .home-g-card.is-active .home-g-overlay { opacity: 1; }
        .home-g-overlay b { color: #fff; font-size: 15px; margin-bottom: 6px; }
        .home-g-overlay span { color: #F0EBE1; font-size: 13px; line-height: 1.5; }

        .home-faq { max-width: 740px; margin: 0 auto; }
        .faq-item { border-bottom: 1px solid var(--line); padding: 6px 4px; }
        .faq-q { width: 100%; background: none; display: flex; justify-content: space-between; align-items: center; font-size: 16px; font-weight: 700; padding: 18px 0; color: var(--ink); text-align: left; }
        .faq-a { font-size: 15px; color: var(--ink-soft); line-height: 1.7; padding-bottom: 18px; }
        .faq-item.is-open .faq-chev { transform: rotate(180deg); }
        .faq-chev { transition: transform 0.2s; color: var(--accent-2); }

        .home-final { background: var(--ink); color: var(--surface); text-align: center; padding: 155px 32px; }
        .home-final h2 { font-family: 'Fraunces', serif; font-weight: 600; font-size: 38px; line-height: 1.4; margin-bottom: 32px; color: var(--surface); }
        .home-final h2 span { color: #D8B98A; }

        .home-footer { background: var(--ink); color: #B0A797; padding: 32px; border-top: 1px solid rgba(255,255,255,0.1); }
        .home-footer-inner { max-width: 1180px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
        .home-footer-inner .home-logo { font-size: 15px; }

        @media (max-width: 900px) {
          .home-steps { grid-template-columns: 1fr; }
          .home-gallery { grid-template-columns: repeat(2, 1fr); }
          .home-nav-mid { display: none; }
          .home-float-card { display: none; }
          .home-ba-grid { grid-template-columns: 1fr; }
          .home-section { padding: 96px 24px; }
          .home-final { padding: 110px 24px; }
        }
        @media (max-width: 560px) {
          .home-hero { padding: 110px 20px 70px; }
          .home-hero-cta { flex-direction: column; gap: 12px; }
          .home-btn-large { width: 100%; max-width: 280px; }
          .home-stat-row { gap: 24px; flex-wrap: wrap; }
          .home-footer-inner { flex-direction: column; gap: 8px; text-align: center; }
        }
      `}</style>

      <header className="home-header">
        <div className="home-nav">
          <div className="home-logo">Picmood</div>
          <div className="home-nav-mid">
            <a href="#process">{t.navProcess}</a>
            <a href="#gallery">{t.navGallery}</a>
            <a href="#faq">{t.navFaq}</a>
          </div>
          <div className="home-nav-right">
            <span className="home-lang">
              <button className={lang === "ko" ? "is-active" : ""} onClick={() => setLang("ko")}>KO</button>
              /
              <button className={lang === "en" ? "is-active" : ""} onClick={() => setLang("en")}>EN</button>
            </span>
            <button className="home-btn-primary" onClick={onStart}>{t.start}</button>
          </div>
        </div>
      </header>

      <section className="home-hero">
        {heroCards.map((ref, i) => (
          <div key={ref.id} className={`home-float-card fc${i + 1}`}>
            <div className="fc-header">
              <span className="fc-avatar" aria-hidden="true">☕</span>
              <span className="fc-brand">Picmood</span>
            </div>
            <img className="fc-photo" src={ref.thumbnail_url} alt={compLabel(ref)} />
            <div className="fc-actions">
              <MiniHeartIcon /><MiniCommentIcon /><MiniShareIcon /><MiniBookmarkIcon />
            </div>
            <div className="fc-cap">
              <b>{seededLikeCount(ref.id)}</b> {compCaption(ref)}
            </div>
          </div>
        ))}

        <div className="home-hero-inner">
          <div className="home-eyebrow">{t.eyebrow}</div>
          <h1>{t.heroTitle1}<br /><span>{t.heroTitleSpan}</span>{t.heroTitle2}</h1>
          <p>{t.heroSubtitle}</p>
          <div className="home-hero-cta">
            <button className="home-btn-primary home-btn-large" onClick={onStart}>{t.start}</button>
            <a href="#gallery" className="home-btn-secondary home-btn-large" style={{ textDecoration: "none", display: "inline-block" }}>{t.exploreStyles}</a>
          </div>
          <div className="home-stat-row">
            <div><b>{t.stat1Num}</b>{t.stat1Label}</div>
            <div><b>{t.stat2Num}</b>{t.stat2Label}</div>
            <div><b>{t.stat3Num}</b>{t.stat3Label}</div>
          </div>
        </div>
      </section>

      <section className="home-section" id="process">
        <div className="home-section-head">
          <div className="home-kicker">{t.processKicker}</div>
          <h2>{t.processTitle1}<br />{t.processTitle2}</h2>
          <p>{t.processSub}</p>
        </div>
        <div className="home-steps">
          <div className="home-step">
            <div className="home-step-num">01</div>
            <h3>{t.step1Title}</h3>
            <p>{t.step1Desc}</p>
            <div className="home-step-visual">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#FFFDF9" strokeWidth="1.3">
                <path d="M4 8h13l-1 8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3L4 8Z" />
                <path d="M17 9h1.5a2.5 2.5 0 0 1 0 5H17" />
              </svg>
            </div>
          </div>
          <div className="home-step">
            <div className="home-step-num">02</div>
            <h3>{t.step2Title}</h3>
            <p>{t.step2Desc}</p>
            <div className="home-step-visual" style={{ background: "var(--accent-2)" }}>
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#FFFDF9" strokeWidth="1.3">
                <rect x="4" y="4" width="7" height="7" rx="1.5" />
                <rect x="13" y="4" width="7" height="7" rx="1.5" />
                <rect x="4" y="13" width="7" height="7" rx="1.5" />
                <rect x="13" y="13" width="7" height="7" rx="1.5" />
              </svg>
            </div>
          </div>
          <div className="home-step">
            <div className="home-step-num">03</div>
            <h3>{t.step3Title}</h3>
            <p>{t.step3Desc}</p>
            <div className="home-step-visual" style={{ background: "var(--accent)" }}>
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#FFFDF9" strokeWidth="1.3">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </div>
          </div>
        </div>
      </section>

      <section className="home-ba home-section">
        <div className="home-section-head">
          <div className="home-kicker">Before &amp; after</div>
          <h2>{t.baTitle}</h2>
          <p>{t.baSub}</p>
        </div>
        <div className="home-ba-grid">
          <div className="home-ba-col before"><span className="home-ba-tag">{t.baBefore}</span></div>
          <div className="home-ba-col after">
            <span className="home-ba-tag">{t.baAfter}</span>
            {galleryItems[0] && <img src={galleryItems[0].thumbnail_url} alt={t.baAfter} />}
          </div>
        </div>
      </section>

      <section className="home-section" id="gallery">
        <div className="home-section-head">
          <div className="home-kicker">{t.galleryKicker}</div>
          <h2>{t.galleryTitle}</h2>
          <p>{t.gallerySub}</p>
        </div>
        <div className="home-gallery">
          {galleryItems.map((ref) => (
            <div
              key={ref.id}
              className={`home-g-card${activeCardId === ref.id ? " is-active" : ""}`}
              onClick={() => toggleCard(ref.id)}
            >
              <img src={ref.thumbnail_url} alt={compLabel(ref)} />
              <div className="home-g-overlay">
                <b>{moodLabel(ref)}</b>
                <span>{compLabel(ref)}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="home-section" id="faq">
        <div className="home-section-head">
          <div className="home-kicker">{t.faqKicker}</div>
          <h2>{t.faqTitle}</h2>
        </div>
        <div className="home-faq">
          {t.faqItems.map((item, i) => (
            <FaqItem key={item.q} q={item.q} a={item.a} defaultOpen={i === 0} />
          ))}
        </div>
      </section>

      <section className="home-final">
        <h2>{t.finalTitle1}<br />{t.finalTitle2Pre}<span>Picmood</span>{t.finalTitle2Post}</h2>
        <button className="home-btn-primary home-btn-large" onClick={onStart}>{t.start}</button>
      </section>

      <footer className="home-footer">
        <div className="home-footer-inner">
          <div className="home-logo">Picmood</div>
          <div>{t.footerNote}</div>
        </div>
      </footer>
    </div>
  );
}

export default Home;
