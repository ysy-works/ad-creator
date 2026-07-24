import { useState, useEffect, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";

/*
  디자인 토큰 (Picmood · 카페 무드보드 소셜카드 컨셉)
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
    보이게 하는 자체 아바타(커피잔 아이콘)+브랜드명("Picmood")+선택 스탬프.
    좋아요 수는 레퍼런스 id 기반으로 결정적으로 생성(매번 안 바뀜).
*/

// 카드 캡션에 쓸 감성적인 한 줄 문구. composition_id 기준으로 매핑.
// (references.json의 composition_label 자체는 안 건드림 — 업로드 안내 등
//  다른 곳에서는 여전히 원래 라벨을 씀. 이건 카드에서 "촬영기법 용어처럼
//  보인다"는 피드백을 반영해, 카드에서만 보여줄 감성적 문구를 따로 둔 것.)
// -> 기존엔 한국어 문구만 있어서 영문 모드에서도 카드 캡션이 한글로 고정
//    되어 있던 버그가 있었음. Home.jsx의 COMPOSITION_CAPTION과 동일한
//    영문 문구를 그대로 가져와 lang별로 분기하도록 수정.
const COMPOSITION_MOOD_CAPTIONS = {
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

const getCardCaption = (ref, lang) =>
  COMPOSITION_MOOD_CAPTIONS[lang]?.[ref.composition_id] ||
  (lang === "en"
    ? COMPOSITION_LABEL_EN[ref.composition_id] || ref.composition_label
    : ref.composition_label);

// 촬영 가이드 문구 (팀장 요청, 2026-07-21). 업로드 단계에서 "i" 아이콘에
// 마우스를 올렸을 때 표시되는 안내 문구. composition_id 기준으로 매핑되며,
// 선택한 레퍼런스와 비슷한 각도로 찍을 수 있도록 구체적인 촬영 팁을 담음.
// 이미지 없이 텍스트 안내만 제공 (예시 이미지는 추후 필요 시 추가 예정).
const SHOOTING_GUIDE = {
  ko: {
    product_large: "레퍼런스 이미지처럼 음료가 화면에 꽉 차도록 가까이서 찍어주세요.",
    product_center: "테이블 위에 자연스럽게 두고, 살짝 거리를 두어 자연스럽게 내려다보는 각도로 찍어주세요.",
    aerial_shot: "음료 바로 위에서 수직으로 내려다보는 각도로 찍어주세요.",
    handheld_lifestyle: "음료를 테이블이나 바닥에 두고, 옆에서 바라보는 각도로 찍어주세요.",
  },
  en: {
    product_large: "Get in close so the drink fills the frame, just like the reference.",
    product_center: "Place it naturally on the table and shoot from a slight distance, looking down at a natural angle.",
    aerial_shot: "Shoot from directly above, straight down at a vertical angle.",
    handheld_lifestyle: "Place it on a table or the floor and shoot from the side, at eye level with the drink.",
  },
};

// 도구 화면(PicmoodTool) 자체 UI 문구 번역 사전. references.json 안의
// mood_label/composition_label은 한국어만 있어서, id 기준 별도 매핑으로 처리.
const MOOD_LABEL_EN = { natural_white: "Neutral White", wood: "Wood", vivid: "Dark Gray" };
const COMPOSITION_LABEL_EN = {
  product_large: "Close-up",
  product_center: "Medium shot",
  aerial_shot: "Aerial shot",
  handheld_lifestyle: "Handheld",
};
const PURPOSE_LABEL_EN = {
  "일상 홍보": "Everyday post",
  "신메뉴 소개": "New menu",
  "오늘의 추천": "Today's pick",
  "세일·이벤트": "Sale / event",
  "기타": "Other",
};

const T = {
  ko: {
    eyebrow: "COFFEE MOOD LAB",
    title: "카페 음료 이미지 스타일링",
    subtitle: "사진을 올리면 어울리는 스타일로 보정하고, 바로 올릴 문구까지 만들어드립니다.",
    step1SectionTitle: "1. 스타일 선택",
    loadingList: "불러오는 중...",
    step2SectionTitle: "2. 사진 업로드",
    uploadHintSuffix: " 느낌으로 찍은 사진을 올려주세요.",
    selectStyleFirst: "스타일을 먼저 선택해주세요.",
    choosePhoto: "사진 선택",
    noFileChosen: "선택된 파일 없음",
    previewAlt: "업로드한 사진 미리보기",
    generating: "생성 중...",
    generateImage: "이미지 생성",
    uploadPhotoFirst: "사진을 업로드해주세요.",
    generateFailed: "이미지 생성에 실패했습니다.",
    styleNotReady: "아직 준비 중인 스타일입니다.",
    genericError: "오류가 발생했습니다.",
    aspectRatioLabel: "결과 비율",
    selectRatioFirst: "결과 비율(4:5 또는 1:1)을 선택해주세요.",
    cupSourceLabel: "컵",
    cupSourceUploaded: "내가 찍은 컵",
    cupSourceModel: "예쁜 컵으로",
    selectCupSourceFirst: "컵을 어떻게 할지 선택해주세요.",
    resultTitle: "완성된 한 컷",
    resultAlt: "생성 결과",
    downloadImage: "이미지 다운로드",
    captionInfoTitle: "문구에 담을 정보 (선택)",
    captionInfoHint: "비워두셔도 괜찮아요. 채워주시면 문구가 더 정확해져요.",
    menuNameLabel: "메뉴명",
    menuNamePlaceholder: "예: 아이스 아메리카노",
    purposeLabel: "게시 목적",
    purposeOtherPlaceholder: "게시 목적을 직접 입력해주세요",
    makeCaption: "캡션·해시태그 만들기",
    makingCaption: "문구 만드는 중...",
    remakeCaption: "다시 만들기",
    storyLabel: "스토리 문구",
    copyText: "텍스트 복사",
    copied: "복사됨!",
    loadReferencesError: "레퍼런스 목록을 불러오지 못했습니다.",
    captionFailed: "캡션 생성에 실패했습니다.",
    captionError: "캡션 생성 중 오류가 발생했습니다.",
    copyFailed: "복사에 실패했습니다. 직접 선택해서 복사해주세요.",
  },
  en: {
    eyebrow: "COFFEE MOOD LAB",
    title: "Cafe Drink Photo Studio",
    subtitle: "Upload a photo and we'll style it to match your mood, captions included.",
    step1SectionTitle: "1. Choose a style",
    loadingList: "Loading...",
    step2SectionTitle: "2. Upload a photo",
    uploadHintSuffix: " — upload a photo with this mood and angle.",
    selectStyleFirst: "Choose a style first.",
    choosePhoto: "Choose photo",
    noFileChosen: "No file chosen",
    previewAlt: "Preview of uploaded photo",
    generating: "Generating...",
    generateImage: "Generate image",
    uploadPhotoFirst: "Please upload a photo.",
    generateFailed: "Failed to generate the image.",
    styleNotReady: "This style isn't available yet.",
    genericError: "Something went wrong.",
    aspectRatioLabel: "Result ratio",
    selectRatioFirst: "Please choose a result ratio (4:5 or 1:1).",
    cupSourceLabel: "Cup",
    cupSourceUploaded: "My cup",
    cupSourceModel: "Styled cup",
    selectCupSourceFirst: "Please choose which cup to use.",
    resultTitle: "Your finished shot",
    resultAlt: "Generated result",
    downloadImage: "Download image",
    captionInfoTitle: "Details for your caption (optional)",
    captionInfoHint: "Feel free to leave this blank. Filling it in makes the caption more accurate.",
    menuNameLabel: "Menu name",
    menuNamePlaceholder: "e.g. Iced Americano",
    purposeLabel: "Purpose",
    purposeOtherPlaceholder: "Describe the purpose yourself",
    makeCaption: "Create caption & hashtags",
    makingCaption: "Writing caption...",
    remakeCaption: "Regenerate",
    storyLabel: "Story caption",
    copyText: "Copy text",
    copied: "Copied!",
    loadReferencesError: "Couldn't load the reference list.",
    captionFailed: "Failed to generate the caption.",
    captionError: "Something went wrong while generating the caption.",
    copyFailed: "Couldn't copy. Please select and copy the text manually.",
  },
};


// 지금 브라우저 주소창의 호스트를 그대로 따라가서 API를 호출한다.
// -> IP가 바뀌어도(카페 Wi-Fi 등) 코드 수정 없이 그대로 동작함.
// 배포된 백엔드 주소 (Render). Vercel 등 실제 배포 환경에서는 기본으로 이걸 씀.
const RENDER_BACKEND = "https://ad-creator-backend-latest.onrender.com";

// 지금 접속한 주소가 localhost거나, 같은 Wi-Fi 안의 사설망 IP(192.168.x.x, 10.x.x.x)면
// "로컬에서 개발 중"이라고 판단해서 로컬 백엔드(8000번 포트)를 우선 사용한다.
// -> 평소 개발할 때는 Render의 콜드스타트(약 1분)를 기다릴 필요 없이 바로 로컬로 붙는다.
const isLocalDev =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1" ||
  /^192\.168\.\d{1,3}\.\d{1,3}$/.test(window.location.hostname) ||
  /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(window.location.hostname);

const API_BASE = isLocalDev
  ? `http://${window.location.hostname}:8000`
  : RENDER_BACKEND;

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

// 촬영 가이드용 "i" 아이콘. 마우스를 올리면(호버) 또는 클릭/탭하면 툴팁으로
// 안내 문구를 보여준다. 팀장 요청 사항: 업로드 안내 문구 옆에 배치,
// 이미지 없이 텍스트 안내만.
//
// 위치 계산 히스토리 (같은 버그를 세 번 거쳐 고친 기록, 참고용으로 남겨둠):
// 1차: 아이콘 중앙 기준으로 툴팁을 가운데 정렬(translateX(-50%))했는데,
//      아이콘이 화면 오른쪽 가장자리에 가까우면 화면 밖으로 넘어감.
// 2차: hover/focus 시점에 위치를 보정하도록 했지만, 모바일 터치에서는 tap이
//      CSS :hover만 트리거하고 실제 mouseenter/focus JS 이벤트는 안 붙는
//      경우가 있어 보정 로직 자체가 실행이 안 됨.
// 3차: open을 React state로 관리하고, 아이콘의 실제 화면 좌표를 측정해
//      position: fixed(뷰포트 기준 절대좌표)로 위치를 고정 — 화면 밖으로
//      넘어가는 문제는 해결됐지만, fixed는 "뷰포트"에 고정되는 성질이라
//      스크롤해서 화면을 움직여도 툴팁이 같은 화면 자리에 그대로 붙어있고
//      아이콘을 안 따라가는 문제가 새로 생김.
// 4차(이번): 툴팁을 React Portal로 document.body 바로 밑에 렌더링하고,
//      position: absolute + "페이지" 기준 좌표(스크롤 오프셋을 더한 값)로
//      배치. absolute는 스크롤하면 페이지와 함께 자연스럽게 같이 움직이므로
//      스크롤 이벤트를 따로 감지할 필요 없이 아이콘 옆에 계속 붙어있게 됨.
//      body의 포탈로 뺀 이유: 부모(.guide-icon 등)의 position/overflow
//      설정에 영향을 받지 않고 항상 화면 최상단에, 항상 페이지 전체 폭
//      기준으로 계산되도록 하기 위함.
function GuideIcon({ text }) {
  const iconRef = useRef(null);
  const tooltipRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null); // { left, top } — 페이지(document) 기준 px

  // 열릴 때마다 아이콘의 "현재" 위치를 새로 측정해서 계산 — 이전 값에 의존하지 않음.
  useLayoutEffect(() => {
    if (!open) return;
    const icon = iconRef.current;
    const tooltip = tooltipRef.current;
    if (!icon || !tooltip) return;

    const edgeMargin = 12; // 화면 가장자리와 떨어질 최소 여백
    const gap = 8; // 아이콘과 툴팁 사이 간격
    const iconRect = icon.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();

    let left = iconRect.left + iconRect.width / 2 - tooltipRect.width / 2;
    const maxLeft = window.innerWidth - tooltipRect.width - edgeMargin;
    left = Math.min(Math.max(left, edgeMargin), Math.max(maxLeft, edgeMargin));

    let top = iconRect.top - tooltipRect.height - gap;
    if (top < edgeMargin) {
      // 위쪽에 자리가 없으면(화면 맨 위 근처) 아이콘 아래쪽에 표시
      top = iconRect.bottom + gap;
    }

    // 지금까지는 전부 "뷰포트" 기준 좌표 -> 포탈로 body에 붙일 것이므로
    // 현재 스크롤 위치를 더해서 "페이지" 기준 좌표로 변환.
    setPos({ left: left + window.scrollX, top: top + window.scrollY });
  }, [open, text]);

  useEffect(() => {
    if (!open) return;
    // 아이콘 바깥을 클릭/탭하면 닫히도록 (모바일에서 열어둔 채 방치 방지)
    const handleOutside = (e) => {
      if (iconRef.current && !iconRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("click", handleOutside);
    return () => document.removeEventListener("click", handleOutside);
  }, [open]);

  if (!text) return null;

  const tooltipNode = (
    <span
      className={`guide-icon__tooltip${open ? " is-open" : ""}`}
      role="tooltip"
      ref={tooltipRef}
      style={
        pos
          ? { position: "absolute", left: pos.left, top: pos.top }
          : { position: "absolute", left: 0, top: 0, visibility: "hidden" }
      }
    >
      {text}
    </span>
  );

  return (
    <span
      className={`guide-icon${open ? " is-open" : ""}`}
      tabIndex={0}
      ref={iconRef}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onClick={(e) => {
        e.stopPropagation();
        setOpen((prev) => !prev);
      }}
    >
      <span className="guide-icon__mark" aria-hidden="true">i</span>
      {typeof document !== "undefined" ? createPortal(tooltipNode, document.body) : tooltipNode}
    </span>
  );
}

// 인스타그램 실제 화면이 아니라, 우리 서비스만의 "무드보드 피드 카드" 프레임
// -> "좋아요 N개"와 "선택됨" 배지가 lang과 무관하게 한글로 고정되어 있던
//    버그 수정: lang을 받아 영문 모드에서는 "N likes" / "Selected"로 표시.
function PostFrame({ children, brand = "Picmood", caption, likeCount, selected, badgeText, onClick, lang = "ko", disabled = false, disabledLabel, photoClassName = "" }) {
  const likeText = likeCount != null
    ? (lang === "en" ? `${likeCount} likes` : `좋아요 ${likeCount}개`)
    : null;
  const stampText = badgeText || (lang === "en" ? "Selected" : "선택됨");
  const comingSoonText = disabledLabel || (lang === "en" ? "Coming soon" : "준비 중");

  return (
    <div
      className={`post-frame${selected ? " is-selected" : ""}${disabled ? " is-disabled" : ""}`}
      onClick={disabled ? undefined : onClick}
      aria-disabled={disabled || undefined}
    >
      <div className="post-frame__header">
        <span className="post-frame__avatar" aria-hidden="true">☕</span>
        <span className="post-frame__brand">{brand}</span>
        {selected && !disabled && <span className="post-frame__stamp">{stampText}</span>}
        {disabled && <span className="post-frame__stamp post-frame__stamp--muted">{comingSoonText}</span>}
      </div>

      <div className={`post-frame__photo${photoClassName ? " " + photoClassName : ""}`}>{children}</div>

      <div className="post-frame__actions">
        <span className="post-frame__icon post-frame__icon--like"><HeartIcon /></span>
        <span className="post-frame__icon"><CommentIcon /></span>
        <span className="post-frame__icon"><ShareIcon /></span>
        <span className="post-frame__icon post-frame__icon--save"><BookmarkIcon /></span>
      </div>

      {(caption || likeText) && (
        <div className="post-frame__caption">
          {likeText && <strong>{likeText}</strong>}
          {caption && <span> {caption}</span>}
        </div>
      )}
    </div>
  );
}

function App({ lang = "ko", setLang }) {
  const t = T[lang] || T.ko;
  const [productFile, setProductFile] = useState(null);
  const fileInputRef = useRef(null);
  const [productPreviewUrl, setProductPreviewUrl] = useState(null);

  const [references, setReferences] = useState([]); // GET /references 결과 (그루핑 전 원본)
  const [selectedReferenceId, setSelectedReferenceId] = useState(null);
  // 결과 비율 토글. 2026-07-23 팀장 정정: 4:5(1024x1280)/1:1(1024x1024) 둘 다
  // 실제로 지원되며, 사용자가 반드시 하나를 선택해야만 생성 가능 — 그래서
  // 기본값을 미리 골라두지 않고 null로 시작한다.
  const [aspectRatio, setAspectRatio] = useState(null);
  // 업로드한 컵 그대로 vs 모델이 준비한 컵으로 교체. 2026-07-24 소연님 회의
  // 요청사항 — 4:5/1:1과 동일하게 반드시 선택해야 생성 가능하도록 처리.
  const [cupSource, setCupSource] = useState(null);

  // 캡션 품질 향상을 위한 최소 질문 (둘 다 선택 입력)
  const [menuName, setMenuName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [purposeOther, setPurposeOther] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resultImage, setResultImage] = useState(null);

  const [captionLoading, setCaptionLoading] = useState(false);
  const [captionReady, setCaptionReady] = useState(false);
  const [caption, setCaption] = useState(null);
  const [hashtags, setHashtags] = useState([]);
  const [story, setStory] = useState(null);
  const [copied, setCopied] = useState(false);

  const PURPOSE_OPTIONS = ["일상 홍보", "신메뉴 소개", "오늘의 추천", "세일·이벤트", "기타"];

  // 페이지 로드 시 레퍼런스 목록 불러오기.
  // -> 예전엔 백엔드(Render)의 GET /references를 호출했는데, 이 데이터는
  //    고정된 정적 정보(무드/구도 목록)라 굳이 매번 Render를 거칠 필요가 없다.
  //    프론트(Cloudflare)에 같이 배포되는 정적 파일(/references.json)을
  //    직접 읽도록 바꿔서, Render가 잠들어 있어도 갤러리는 항상 즉시 뜬다.
  //    (실제 이미지 생성/캡션 생성은 여전히 Render를 거침 — 여기만 예외)
  useEffect(() => {
    fetch("/references.json")
      .then((res) => res.json())
      .then((data) => setReferences(data))
      .catch(() => setError(t.loadReferencesError));
  }, []);

  // 업로드한 파일이 바뀌면 미리보기 URL 생성
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    setProductFile(file);
    setResultImage(null);
    setCaptionReady(false);
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

  // 현재 선택된 레퍼런스 객체 (업로드 단계 안내에 사용)
  const selectedReference = references.find((r) => r.id === selectedReferenceId);

  // 1단계: 이미지만 생성 (캡션은 아직 만들지 않음)
  const handleGenerate = async () => {
    if (!selectedReferenceId) {
      setError(t.selectStyleFirst);
      return;
    }
    // 생성 직전 이중 체크 — 카드 클릭은 막아뒀지만(disabled), 혹시 모를 경우 대비.
    if (selectedReference?.enabled === false) {
      setError(t.styleNotReady);
      return;
    }
    if (!productFile) {
      setError(t.uploadPhotoFirst);
      return;
    }
    if (!aspectRatio) {
      setError(t.selectRatioFirst);
      return;
    }
    if (!cupSource) {
      setError(t.selectCupSourceFirst);
      return;
    }
    setError("");
    setLoading(true);
    setResultImage(null);
    setCaptionReady(false);
    setCaption(null);
    setHashtags([]);
    setStory(null);
    setCopied(false);

    try {
      const formData = new FormData();
      formData.append("product_image", productFile);
      formData.append("reference_id", selectedReferenceId);
      formData.append("aspect_ratio", aspectRatio);
      formData.append("cup_source", cupSource);

      const response = await fetch(`${API_BASE}/generate`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        // 미지원 preset(400)은 "생성 실패"가 아니라 "아직 준비 중인 스타일"로 구분 표시
        // (백엔드 model.py가 활성 2개 외 요청에 이 메시지를 담아 400을 반환함).
        let message = t.generateFailed;
        try {
          const errBody = await response.json();
          if (response.status === 400 && /지원하지 않는|not.*available/i.test(errBody.error || "")) {
            message = t.styleNotReady;
          }
        } catch (_) {
          // 응답 본문이 JSON이 아니면 기본 메시지 사용
        }
        throw new Error(message);
      }

      const data = await response.json();
      setResultImage(data.result_image);
    } catch (err) {
      setError(err.message || t.genericError);
    } finally {
      setLoading(false);
    }
  };

  // 2단계: 사용자가 결과를 확인한 후 버튼을 눌렀을 때만 캡션 생성
  const handleGenerateCaption = async () => {
    setError("");
    setCaptionLoading(true);

    try {
      const response = await fetch(`${API_BASE}/caption`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reference_id: selectedReferenceId,
          result_image_base64: resultImage,
          menu_name: menuName || null,
          purpose: purpose === "기타" ? (purposeOther || null) : (purpose || null),
          lang,
        }),
      });

      if (!response.ok) {
        throw new Error(t.captionFailed);
      }

      const data = await response.json();
      setCaption(data.caption);
      setHashtags(data.hashtags || []);
      setStory(data.story || null);
      setCaptionReady(true);
    } catch (err) {
      setError(err.message || t.captionError);
    } finally {
      setCaptionLoading(false);
    }
  };

  // 캡션 + 해시태그 + 스토리 문구를 클립보드에 복사 (바로 붙여넣기용)
  const handleCopyCaption = async () => {
    const text = [caption, hashtags.join(" "), story && `[스토리] ${story}`]
      .filter(Boolean)
      .join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError(t.copyFailed);
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

        .cafe-app {
          --bg: #EFE8DA;
          --surface: #FFFDF9;
          --ink: #2B2420;
          --ink-soft: #554A40;
          --accent: #8A6E4B;
          --accent-2: #5C6B4C;
          --line: #DDD2BE;

          width: 100%;
          background: var(--bg);
          color: var(--ink);
          font-family: 'PretendardVariable', 'Pretendard', -apple-system, sans-serif;
          min-height: 100vh;
          padding: clamp(20px, 5vw, 48px);
          word-break: keep-all;
          overflow-wrap: break-word;
          -webkit-font-smoothing: antialiased;
          -moz-osx-font-smoothing: grayscale;
        }

        .lang-toggle-bar {
          position: fixed;
          top: 16px;
          right: 16px;
          z-index: 100;
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 999px;
          padding: 8px 14px;
          font-size: 13px;
          display: flex;
          gap: 4px;
          align-items: center;
        }
        .lang-toggle-bar button {
          background: none;
          border: none;
          font-size: 13px;
          font-weight: 700;
          color: var(--ink-soft);
          cursor: pointer;
          padding: 2px;
        }
        .lang-toggle-bar button.is-active {
          color: var(--ink);
          text-decoration: underline;
          text-underline-offset: 3px;
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
          color: var(--ink);
        }

        .cafe-app__subtitle {
          text-align: center;
          color: var(--ink-soft);
          font-size: clamp(14px, 2.4vw, 16px);
          font-weight: 500;
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
          color: var(--ink);
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
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
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
        .post-frame.is-disabled {
          cursor: default;
          opacity: 0.55;
        }
        .post-frame.is-disabled:hover {
          transform: none;
          box-shadow: 0 1px 2px rgba(43,36,32,0.04);
        }
        .post-frame.is-disabled .post-frame__photo img {
          filter: grayscale(0.6);
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
        .post-frame__stamp--muted {
          background: var(--ink-soft);
        }

        .post-frame__photo {
          width: 100%;
          aspect-ratio: 1 / 1;
          overflow: hidden;
          background: var(--bg);
        }
        /* 생성 결과 카드 전용: 레퍼런스 카드(1:1)와 달리 실제 반환된 이미지의
           원본 비율 그대로 보여준다. 지금은 model-c-v1이면 1:1, openai 신규
           workflow로 전환되면 4:5로 자연스럽게 바뀜 — 프론트가 비율을 미리
           단정하지 않아도 되는 구조. */
        .post-frame__photo--result {
          aspect-ratio: auto;
        }
        .post-frame__photo--result img {
          height: auto;
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
          font-size: 13px;
          color: var(--ink-soft);
          text-align: left;
        }
        .post-frame__caption strong {
          display: block;
          color: var(--ink);
          font-weight: 700;
          margin-bottom: 2px;
        }

        .upload-panel {
          max-width: 460px;
          margin: 0 auto;
          text-align: center;
        }
        .upload-hint {
          font-size: 15px;
          font-weight: 500;
          margin-bottom: 14px;
          color: var(--ink-soft);
        }
        .upload-hint.is-active { color: var(--accent-2); font-weight: 900; }

        .ratio-toggle {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          margin: 0 0 18px;
          padding: 4px;
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 999px;
        }
        .ratio-toggle__label {
          font-size: 12px;
          font-weight: 700;
          color: var(--ink-soft);
          padding-left: 8px;
        }
        .ratio-toggle__btn {
          position: relative;
          font-family: inherit;
          font-size: 13px;
          font-weight: 700;
          color: var(--ink-soft);
          background: transparent;
          border: none;
          border-radius: 999px;
          padding: 7px 16px;
          cursor: pointer;
          transition: background 0.15s ease, color 0.15s ease;
        }
        .ratio-toggle__btn.is-active {
          background: var(--accent-2);
          color: #fff;
        }

        .guide-icon {
          position: relative;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 16px;
          height: 16px;
          margin-left: 6px;
          border-radius: 50%;
          background: var(--accent-2);
          color: #fff;
          font-size: 11px;
          font-weight: 700;
          font-style: italic;
          font-family: Georgia, 'Times New Roman', serif;
          cursor: pointer;
          vertical-align: middle;
        }
        .guide-icon__tooltip {
          width: max-content;
          max-width: 240px;
          /* body로 포탈되어 .cafe-app 밖으로 나가므로 var(--ink)/var(--surface)를
             못 받아옴 -> 실제 값을 직접 지정 (index.css: --ink #2B2420, --surface #FFFDF9) */
          background: #2B2420;
          color: #FFFDF9;
          font-size: 12px;
          font-weight: 500;
          font-style: normal;
          line-height: 1.5;
          text-align: left;
          word-break: keep-all;
          padding: 9px 12px;
          border-radius: 8px;
          box-shadow: 0 6px 16px rgba(43,36,32,0.18);
          opacity: 0;
          visibility: hidden;
          transition: opacity 0.15s ease;
          pointer-events: none;
          z-index: 1000;
        }
        .guide-icon__tooltip.is-open {
          opacity: 1;
          visibility: visible;
        }

        .file-input-wrap {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
        }
        .file-input-hidden {
          position: absolute;
          width: 1px;
          height: 1px;
          overflow: hidden;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
        }
        .file-input-btn {
          padding: 9px 22px;
          font-size: 13.5px;
          font-weight: 600;
          color: var(--accent);
          background: var(--surface);
          border: 1.5px solid var(--accent);
          border-radius: 999px;
          cursor: pointer;
          transition: background 0.15s ease, color 0.15s ease;
        }
        .file-input-btn:hover:not(:disabled) {
          background: var(--accent);
          color: #fff;
        }
        .file-input-btn:disabled {
          opacity: 0.5;
          cursor: default;
          border-color: var(--line);
          color: var(--ink-soft);
        }
        .file-input-name {
          font-size: 13.5px;
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
          max-width: min(460px, 100%);
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

        .caption-box {
          margin-top: 20px;
          text-align: left;
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 16px 18px;
        }
        .caption-box__label {
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.06em;
          color: var(--accent-2);
          margin-bottom: 8px;
        }
        .caption-box__text {
          font-size: 14px;
          font-weight: 500;
          line-height: 1.6;
          color: var(--ink);
          margin: 0 0 10px;
          white-space: pre-wrap;
        }
        .caption-box__hashtags {
          font-size: 13px;
          color: var(--accent);
          margin: 0 0 14px;
          line-height: 1.6;
        }
        .copy-btn {
          padding: 8px 18px;
          font-size: 12.5px;
          font-weight: 600;
          color: var(--ink);
          background: var(--bg);
          border: 1px solid var(--line);
          border-radius: 999px;
          cursor: pointer;
        }
        .copy-btn:hover { background: var(--line); }

        .qa-field {
          margin-top: 18px;
          text-align: left;
        }
        .qa-field__label {
          display: block;
          font-size: 12.5px;
          font-weight: 700;
          color: var(--ink);
          margin-bottom: 6px;
        }
        .qa-field__input {
          width: 100%;
          padding: 10px 12px;
          font-size: 14px;
          border: 1px solid var(--line);
          border-radius: 8px;
          background: var(--surface);
          color: var(--ink);
          font-family: inherit;
          box-sizing: border-box;
        }
        .qa-field__input:focus {
          outline: none;
          border-color: var(--accent);
        }
        .qa-options {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .qa-chip {
          padding: 7px 14px;
          font-size: 13px;
          border-radius: 999px;
          border: 1px solid var(--line);
          background: var(--surface);
          color: var(--ink-soft);
          cursor: pointer;
        }
        .qa-chip.is-selected {
          border-color: var(--accent);
          background: var(--accent);
          color: #fff;
        }

        .caption-trigger-btn {
          display: block;
          margin: 12px auto 0;
        }

        @media (max-width: 480px) {
          .mood-grid { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); }
        }
      `}</style>

      <div className="lang-toggle-bar">
        <button
          className={lang === "ko" ? "is-active" : ""}
          onClick={() => setLang && setLang("ko")}
        >
          KO
        </button>
        /
        <button
          className={lang === "en" ? "is-active" : ""}
          onClick={() => setLang && setLang("en")}
        >
          EN
        </button>
      </div>

      <div className="cafe-app__inner">
        <span className="cafe-app__eyebrow">{t.eyebrow}</span>
        <h2 className="cafe-app__title">{t.title}</h2>
        <p className="cafe-app__subtitle">
          {t.subtitle}
        </p>

        {/* 1. 레퍼런스 갤러리 */}
        <h3 className="section-title">{t.step1SectionTitle}</h3>
        {Object.keys(groupedByMood).length === 0 && (
          <p style={{ textAlign: "center", color: "var(--ink-soft)" }}>{t.loadingList}</p>
        )}

        {Object.entries(groupedByMood).map(([moodId, group]) => (
          <div key={moodId} className="mood-block">
            <div className="mood-block__label">{lang === "en" ? (MOOD_LABEL_EN[moodId] || group.mood_label) : group.mood_label}</div>
            <div className="mood-grid">
              {group.items.map((ref) => (
                <PostFrame
                  key={ref.id}
                  brand="Picmood"
                  caption={getCardCaption(ref, lang)}
                  likeCount={seededLikeCount(ref.id)}
                  selected={selectedReferenceId === ref.id}
                  onClick={() => setSelectedReferenceId(ref.id)}
                  lang={lang}
                  disabled={ref.enabled === false}
                >
                  <img src={ref.thumbnail_url} alt={lang === "en" ? (COMPOSITION_LABEL_EN[ref.composition_id] || ref.composition_label) : ref.composition_label} />
                </PostFrame>
              ))}
            </div>
          </div>
        ))}

        {/* 2. 사진 업로드 */}
        <h3 className="section-title" style={{ marginTop: "8px" }}>{t.step2SectionTitle}</h3>
        <div className="upload-panel">
          {selectedReference ? (
            <p className="upload-hint is-active">
              <strong>
                {lang === "en"
                  ? `${MOOD_LABEL_EN[selectedReference.mood_id] || selectedReference.mood_label} · ${COMPOSITION_LABEL_EN[selectedReference.composition_id] || selectedReference.composition_label}`
                  : `${selectedReference.mood_label} · ${selectedReference.composition_label}`}
              </strong>
              {t.uploadHintSuffix}
              {"\u00A0"}
              <GuideIcon text={SHOOTING_GUIDE[lang]?.[selectedReference.composition_id]} />
            </p>
          ) : (
            <p className="upload-hint">{t.selectStyleFirst}</p>
          )}

          <div className="file-input-wrap">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png"
              onChange={handleFileChange}
              disabled={!selectedReferenceId}
              className="file-input-hidden"
            />
            <button
              type="button"
              className="file-input-btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={!selectedReferenceId}
            >
              {t.choosePhoto}
            </button>
            <span className="file-input-name">
              {productFile ? productFile.name : t.noFileChosen}
            </span>
          </div>
          {productPreviewUrl && (
            <div className="preview-thumb">
              <img src={productPreviewUrl} alt={t.previewAlt} />
            </div>
          )}

          {selectedReference && productPreviewUrl && (
            <div className="ratio-toggle" role="group" aria-label={t.aspectRatioLabel}>
              <span className="ratio-toggle__label">{t.aspectRatioLabel}</span>
              <button
                type="button"
                className={`ratio-toggle__btn${aspectRatio === "4:5" ? " is-active" : ""}`}
                onClick={() => setAspectRatio("4:5")}
              >
                4:5
              </button>
              <button
                type="button"
                className={`ratio-toggle__btn${aspectRatio === "1:1" ? " is-active" : ""}`}
                onClick={() => setAspectRatio("1:1")}
              >
                1:1
              </button>
            </div>
          )}

          {/* 컵(용기) 소스 선택 — 소연님 회의 요청사항(2026-07-24). 사용자가 찍은 컵이
              마음에 안 들 수 있어서, 실제 업로드한 컵 그대로 쓸지 / 모델이 준비한
              예쁜 컵으로 바꿔서 생성할지 선택. 스타일별 지원 여부는 아직 소연님
              확답 전이라, 우선 모든 활성 스타일에 노출하고 둘 다 필수 선택으로
              둠 — 나중에 스타일별 제약 오면 references.json에 플래그만 추가하면 됨. */}
          {selectedReference && productPreviewUrl && (
            <div className="ratio-toggle" role="group" aria-label={t.cupSourceLabel}>
              <span className="ratio-toggle__label">{t.cupSourceLabel}</span>
              <button
                type="button"
                className={`ratio-toggle__btn${cupSource === "uploaded" ? " is-active" : ""}`}
                onClick={() => setCupSource("uploaded")}
              >
                {t.cupSourceUploaded}
              </button>
              <button
                type="button"
                className={`ratio-toggle__btn${cupSource === "model" ? " is-active" : ""}`}
                onClick={() => setCupSource("model")}
              >
                {t.cupSourceModel}
              </button>
            </div>
          )}
        </div>

        {/* 3. 생성 버튼 (업로드 직후 바로 생성) */}
        <button className="generate-btn" onClick={handleGenerate} disabled={loading}>
          {loading ? t.generating : t.generateImage}
        </button>

        {error && <p className="error-text">{error}</p>}

        {/* 4. 결과 (다운로드는 프레임 제외, 순수 이미지만) */}
        {resultImage && (
          <div className="result-section">
            <h3 className="section-title">{t.resultTitle}</h3>
            <PostFrame brand="Picmood" likeCount={null} lang={lang} photoClassName="post-frame__photo--result">
              <img src={resultImage} alt={t.resultAlt} />
            </PostFrame>
            <button className="download-btn" onClick={handleDownload}>{t.downloadImage}</button>

            {/* 문구 품질을 위한 최소 정보 (둘 다 선택 입력). 캡션을 한 번 만든 뒤에도
                이 입력창은 그대로 두고, 값을 바꿔서 "다시 만들기"를 누르면 이미지는
                그대로 두고 캡션만 다시 생성할 수 있게 함 (이미지 재생성 불필요). */}
            <div className="upload-panel qa-panel">
              <h3 className="section-title" style={{ marginTop: "28px" }}>{t.captionInfoTitle}</h3>
              <p className="upload-hint">{t.captionInfoHint}</p>

              <div className="qa-field">
                <label className="qa-field__label">{t.menuNameLabel}</label>
                <input
                  type="text"
                  className="qa-field__input"
                  placeholder={t.menuNamePlaceholder}
                  value={menuName}
                  onChange={(e) => setMenuName(e.target.value)}
                />
              </div>

              <div className="qa-field">
                <label className="qa-field__label">{t.purposeLabel}</label>
                <div className="qa-options">
                  {PURPOSE_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={`qa-chip${purpose === option ? " is-selected" : ""}`}
                      onClick={() => setPurpose(purpose === option ? "" : option)}
                    >
                      {lang === "en" ? (PURPOSE_LABEL_EN[option] || option) : option}
                    </button>
                  ))}
                </div>
                {purpose === "기타" && (
                  <input
                    type="text"
                    className="qa-field__input"
                    style={{ marginTop: "8px" }}
                    placeholder={t.purposeOtherPlaceholder}
                    value={purposeOther}
                    onChange={(e) => setPurposeOther(e.target.value)}
                  />
                )}
              </div>

              <button
                className="download-btn caption-trigger-btn"
                onClick={handleGenerateCaption}
                disabled={captionLoading}
              >
                {captionLoading ? t.makingCaption : captionReady ? t.remakeCaption : t.makeCaption}
              </button>
            </div>

            {captionReady && (
              <div className="caption-box">
                <p className="caption-box__text">{caption}</p>
                {hashtags.length > 0 && (
                  <p className="caption-box__hashtags">{hashtags.join(" ")}</p>
                )}
                {story && (
                  <>
                    <div className="caption-box__label" style={{ marginTop: "12px" }}>{t.storyLabel}</div>
                    <p className="caption-box__text">{story}</p>
                  </>
                )}
                <button className="copy-btn" onClick={handleCopyCaption}>
                  {copied ? t.copied : t.copyText}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
