import { useCallback, useEffect, useState, useRef } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  CircleHelp,
  Command,
  FileText,
  Globe2,
  History,
  LayoutDashboard,
  LoaderCircle,
  MessageSquare,
  Pause,
  Play,
  Plus,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Upload,
  UserRound,
  X,
  Zap,
} from "lucide-react";
import { api, BASE, connect, previewBlob, token } from "./api";

type RecordData = Record<string, string>;
type Profile = {
  personal: RecordData;
  preferences: RecordData;
  education: RecordData[];
  employment: RecordData[];
  projects: RecordData[];
  skills: RecordData[];
};
type Doc = {
  id: string;
  name: string;
  kind: string;
  default: boolean;
  size: number;
};
type Answer = {
  key: string;
  label: string;
  answer: string;
  source: string;
  explanation: string;
  group: string;
  index: number;
  kind: string;
  options: string[];
  document_id?: string;
};
type Application = {
  id: string;
  status: string;
  revision: number;
  url: string;
  created_at: string;
  submitted_at?: string;
  resume_id?: string;
  job?: { title: string; company: string; location: string };
  answers: Answer[];
  pending?: { label: string; kind: string; options?: string[] };
  suggestion?: string;
  error?: string;
  warnings?: string[];
  step?: number;
  confirmation?: string;
  messages?: { id: number; role: string; message: string }[];
};
type Memory = {
  id: string;
  question: string;
  answer: string;
  source: string;
  sensitive_permission?: boolean;
};
const empty: Profile = {
  personal: {},
  preferences: {},
  education: [],
  employment: [],
  projects: [],
  skills: [],
};
const fields: Record<string, [string, string, string?][]> = {
  personal: [
    ["first_name", "Legal first name"],
    ["last_name", "Legal last name"],
    ["preferred_name", "Preferred name"],
    ["email", "Email address", "email"],
    ["phone", "Phone number", "tel"],
    ["country", "Country"],
    ["state", "State / province"],
    ["city", "City"],
    ["address", "Mailing address"],
    ["zip", "ZIP / postal code"],
    ["linkedin", "LinkedIn URL", "url"],
    ["github", "GitHub URL", "url"],
    ["portfolio", "Portfolio / website", "url"],
  ],
  education: [
    ["school", "College or university"],
    ["degree", "Degree type"],
    ["major", "Major"],
    ["minor", "Minor"],
    ["additional_majors", "Additional majors"],
    ["graduation", "Expected graduation date", "month"],
    ["academic_year", "Current academic year"],
    ["gpa", "GPA"],
    ["gpa_scale", "GPA scale"],
    ["coursework", "Relevant coursework"],
    ["honors", "Academic honors"],
  ],
  employment: [
    ["employer", "Employer"],
    ["title", "Job title"],
    ["start", "Start date", "month"],
    ["end", "End date", "month"],
    ["description", "Responsibilities and accomplishments"],
    ["type", "Experience type (internship, research, employment)"],
  ],
  projects: [
    ["name", "Project / certification name"],
    ["description", "Description and accomplishments"],
    ["skills", "Skills used"],
    ["url", "Project URL", "url"],
  ],
  skills: [
    ["name", "Skill / programming language"],
    ["category", "Category (technical, professional, language, certification)"],
  ],
  preferences: [
    [
      "authorized_us",
      "Legally authorized to work in the United States?",
      "yesno",
    ],
    [
      "sponsorship_us",
      "Need visa sponsorship now or in the future in the United States?",
      "yesno",
    ],
    ["adult", "At least 18 years old?", "yesno"],
    ["relocation", "Relocation preference"],
    ["in_person", "Interested in working in person?", "yesno"],
    ["hybrid", "Interested in hybrid work?", "yesno"],
    ["remote", "Interested in remote work?", "yesno"],
    ["available_start", "Preferred start date", "date"],
    ["available_end", "Preferred end date", "date"],
    ["full_time", "Available full-time?", "yesno"],
    ["hours", "Hours per week"],
    ["compensation", "Preferred compensation"],
    ["veteran", "Veteran status (optional)"],
    ["disability", "Disability status (optional)"],
    ["gender", "Gender (optional)"],
    ["ethnicity", "Race / ethnicity (optional)"],
  ],
};
const tabNames: Record<string, string> = {
  personal: "Personal",
  education: "Education",
  employment: "Experience",
  projects: "Projects",
  skills: "Skills",
  preferences: "Preferences",
  documents: "Documents",
  memory: "Saved answers",
};
const statusLabel = (s: string) => s.replaceAll("_", " ");
function Badge({ status }: { status: string }) {
  return (
    <span
      className={`badge ${status === "submitted" ? "success" : status === "review" || status.startsWith("waiting") || status === "manual" ? "attention" : status === "cancelled" || status === "rejected" ? "quiet" : "working"}`}
    >
      <span />
      {statusLabel(status)}
    </span>
  );
}

export default function App() {
  const [view, setView] = useState("dashboard"),
    [tab, setTab] = useState("personal"),
    [profile, setProfile] = useState<Profile>(empty),
    [docs, setDocs] = useState<Doc[]>([]),
    [apps, setApps] = useState<Application[]>([]),
    [memory, setMemory] = useState<Memory[]>([]),
    [active, setActive] = useState<Application | null>(null);
  const [connected, setConnected] = useState(false),
    [config, setConfig] = useState({
      ai_enabled: false,
      mock_enabled: false,
      model: "",
    }),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [url, setUrl] = useState(""),
    [resume, setResume] = useState(""),
    [query, setQuery] = useState(""),
    [image, setImage] = useState<string | null>(null);
  const chatScroll = useRef<HTMLDivElement>(null);
  const [draftOrigin, setDraftOrigin] = useState(false);
  const [chat, setChat] = useState(""),
    [remember, setRemember] = useState(false),
    [sensitive, setSensitive] = useState(false),
    [documentChoice, setDocumentChoice] = useState(""),
    [kind, setKind] = useState("resume"),
    [editing, setEditing] = useState<Answer | null>(null),
    [edited, setEdited] = useState(""),
    [memEditing, setMemEditing] = useState<Memory | null>(null),
    [memQuestion, setMemQuestion] = useState(""),
    [memAnswer, setMemAnswer] = useState(""),
    [memConsent, setMemConsent] = useState(false);
  const refresh = useCallback(async () => {
    const [p, d, a, m] = await Promise.all([
      api("/profile"),
      api("/documents"),
      api("/applications"),
      api("/memory"),
    ]);
    setProfile(p);
    setDocs(d);
    setApps(a);
    setMemory(m);
  }, []);
  useEffect(() => {
    let mounted = true;
    connect()
      .then(async (cfg) => {
        if (!mounted) return;
        setConfig(cfg);
        setConnected(true);
        await refresh();
      })
      .catch((e) => setError(e.message));
    return () => {
      mounted = false;
    };
  }, [refresh]);
  useEffect(() => {
    if (!connected) return;
    const interval = setInterval(
      () =>
        api("/applications")
          .then(setApps)
          .catch(() => {}),
      3000,
    );
    return () => clearInterval(interval);
  }, [connected]);
  useEffect(() => {
    if (!active?.id || !connected) return;
    const id = active.id;
    let disposed = false;
    const ws = new WebSocket(`${BASE.replace("http", "ws")}/api/ws/${id}`, [
      "internship",
      token,
    ]);
    ws.onmessage = (e) => {
      if (!disposed) setActive(JSON.parse(e.data));
    };
    const fallback = setInterval(
      () =>
        api(`/applications/${id}`)
          .then((a) => {
            if (!disposed) setActive(a);
          })
          .catch(() => {}),
      2000,
    );
    return () => {
      disposed = true;
      ws.close();
      clearInterval(fallback);
    };
  }, [active?.id, connected]);
  useEffect(() => {
    if (!active?.id) return;
    let disposed = false;
    let previous: string | null = null;
    const capture = async () => {
      const next = await previewBlob(active.id).catch(() => null);
      if (disposed) {
        if (next) URL.revokeObjectURL(next);
        return;
      }
      if (previous) URL.revokeObjectURL(previous);
      previous = next;
      setImage(next);
    };
    capture();
    const timer = setInterval(capture, 1700);
    return () => {
      disposed = true;
      clearInterval(timer);
      if (previous) URL.revokeObjectURL(previous);
    };
  }, [active?.id]);
  useEffect(() => {
    setRemember(false);
    setSensitive(false);
    setDraftOrigin(!!active?.suggestion);
    setChat(active?.suggestion || "");
  }, [active?.pending?.label, active?.suggestion]);
  useEffect(() => {
    if (chatScroll.current)
      chatScroll.current.scrollTop = chatScroll.current.scrollHeight;
  }, [active?.messages?.length]);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openApp(id: string) {
    await run(async () => {
      setActive(await api(`/applications/${id}`));
      setView("workspace");
    });
  }
  async function start() {
    await run(async () => {
      const a = await api("/applications", "POST", {
        url,
        resume_id: resume || null,
      });
      setActive(a);
      setView("workspace");
      setUrl("");
      setApps(await api("/applications"));
    });
  }
  async function action(action: string) {
    if (!active) return;
    await run(async () => {
      await api(`/applications/${active.id}/action`, "POST", { action });
      setActive(await api(`/applications/${active.id}`));
    });
  }
  async function send() {
    if (!active) return;
    await run(async () => {
      if (
        active.pending &&
        ["waiting_answer", "waiting_verification"].includes(active.status) &&
        !/^(pause(?: the application)?|continue|resume|cancel(?: this application)?|stop|show me what you filled out|why did you choose that answer|don.t remember that answer|(?:change|update|set) .*graduation.*|use .*\.(?:pdf|docx))[.! ]*$/i.test(
          chat,
        )
      ) {
        await api(`/applications/${active.id}/answer`, "POST", {
          text: chat,
          remember,
          sensitive_permission: sensitive,
          document_id: documentChoice || null,
          origin: draftOrigin ? "draft" : "user",
        });
      } else {
        await api(`/applications/${active.id}/chat`, "POST", { message: chat });
      }
      setChat("");
      setRemember(false);
      setDraftOrigin(false);
      setDocumentChoice("");
      setActive(await api(`/applications/${active.id}`));
      setMemory(await api("/memory"));
    });
  }
  function updateField(
    section: string,
    key: string,
    value: string,
    index?: number,
  ) {
    setProfile((p) => {
      if (index !== undefined) {
        const list = [...(p[section as keyof Profile] as RecordData[])];
        list[index] = { ...list[index], [key]: value };
        return { ...p, [section]: list };
      }
      return {
        ...p,
        [section]: {
          ...(p[section as keyof Profile] as RecordData),
          [key]: value,
        },
      };
    });
  }
  function fieldGrid(section: string, record: RecordData, index?: number) {
    return (
      <div className="form-grid">
        {fields[section].map(([key, label, type]) => (
          <label
            className={
              key === "description" || key === "coursework" ? "wide" : ""
            }
            key={key}
          >
            <span>{label}</span>
            {type === "yesno" ? (
              <select
                aria-label={label}
                value={record[key] || ""}
                onChange={(e) =>
                  updateField(section, key, e.target.value, index)
                }
              >
                <option value="">Not answered</option>
                <option>Yes</option>
                <option>No</option>
              </select>
            ) : key === "description" ? (
              <textarea
                aria-label={label}
                value={record[key] || ""}
                onChange={(e) =>
                  updateField(section, key, e.target.value, index)
                }
              />
            ) : (
              <input
                aria-label={label}
                type={type || "text"}
                value={record[key] || ""}
                onChange={(e) =>
                  updateField(section, key, e.target.value, index)
                }
              />
            )}
          </label>
        ))}
      </div>
    );
  }
  const completion = Math.round(
    ([
      profile.personal.first_name,
      profile.personal.last_name,
      profile.personal.email,
      profile.personal.phone,
      profile.education[0]?.school,
      profile.education[0]?.graduation,
      profile.skills[0]?.name,
      docs.some((d) => d.kind === "resume"),
    ].filter(Boolean).length /
      8) *
      100,
  );
  const attention = apps.filter((a) =>
    [
      "waiting_answer",
      "waiting_verification",
      "review",
      "manual",
      "paused",
      "submission_unknown",
    ].includes(a.status),
  ).length;
  const ongoing = apps.filter((a) =>
    ["queued", "verifying", "filling", "submitting"].includes(a.status),
  ).length;
  const submitted = apps.filter((a) => a.status === "submitted").length;
  const recent = apps.slice(0, 4);
  const filtered = apps.filter((a) =>
    `${a.job?.company} ${a.job?.title} ${a.status} ${a.url}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const nav = [
    ["dashboard", "Overview", LayoutDashboard],
    ["profile", "Applicant profile", UserRound],
    ["workspace", "Agent workspace", Sparkles],
    ["history", "Application history", History],
  ] as const;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setView("dashboard")}>
          <span className="brand-icon">
            <Zap size={23} fill="currentColor" />
          </span>
          blink<span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">
          YOUR WORKSPACE <span>01</span>
        </div>
        <nav>
          {nav.map(([key, name, Icon]) => (
            <button
              key={key}
              className={view === key ? "nav-active" : ""}
              onClick={() => setView(key)}
            >
              <Icon size={19} />
              {name}
              {key === "workspace" && attention > 0 && (
                <span className="nav-count">{attention}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status">
            <span className={connected ? "online" : ""} />
            {connected ? "Local workspace connected" : "Backend offline"}
            <ShieldCheck size={15} />
          </div>
          <div className="profile-chip">
            <div className="avatar">
              {profile.personal.first_name?.[0] || "Y"}
              {profile.personal.last_name?.[0] || "U"}
            </div>
            <div>
              <strong>
                {profile.personal.first_name
                  ? `${profile.personal.first_name} ${profile.personal.last_name || ""}`
                  : "Your applicant profile"}
              </strong>
              <small>Personal workspace</small>
            </div>
            <button
              onClick={() => setView("profile")}
              aria-label="Open profile"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={13} />
            <strong>{nav.find((n) => n[0] === view)?.[1]}</strong>
          </span>
          <div className="topbar-right">
            <span className="local-pill">
              <ShieldCheck size={14} /> PRIVATE & LOCAL
            </span>
            <button
              className="icon-btn"
              aria-label="Show help"
              onClick={() =>
                setNotice(
                  "Start the backend on port 8000. Complete your profile, upload a resume, then paste a direct internship URL. The agent will ask for missing answers and require approval before submitting.",
                )
              }
            >
              <CircleHelp size={19} />
            </button>
          </div>
        </header>
        <main
          className={`main-content ${view === "workspace" ? "workspace-content" : ""}`}
        >
          {error && (
            <div className="alert error" role="alert">
              <CircleHelp size={17} />
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="Dismiss error">
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert notice">
              <Check size={17} />
              <span>{notice}</span>
              <button onClick={() => setNotice("")} aria-label="Dismiss notice">
                <X size={16} />
              </button>
            </div>
          )}
          {view === "dashboard" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    LESS REPETITION. MORE POSSIBILITY.
                  </div>
                  <h1>
                    Apply for internships in the <em>blink</em> of an eye
                    <span>.</span>
                  </h1>
                  <p>
                    Answer once. Let your internship applications take it from
                    there.
                  </p>
                </div>
                <span className="date-label">
                  {new Intl.DateTimeFormat("en-US", {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  }).format(new Date())}
                </span>
              </div>
              <section className="launch-card">
                <div className="launch-copy">
                  <span className="mini-label">
                    <Sparkles size={14} /> YOUR APPLICATION, IN A FLASH
                  </span>
                  <h2>
                    A little spark.
                    <br />A big next step.
                  </h2>
                  <p>
                    Paste a job link. Your agent fills the forms, checks in when
                    it needs you, and waits for your final approval.
                  </p>
                  <div className="supported">
                    <span>WORKDAY</span>
                    <i />
                    <span>Greenhouse</span>
                    <i />
                    <span>lever</span>
                  </div>
                </div>
                <div className="launch-action">
                  <label htmlFor="job-url">Where are we applying?</label>
                  <div className="url-field">
                    <Globe2 size={18} />
                    <input
                      id="job-url"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="Paste an internship job URL"
                    />
                  </div>
                  <select
                    aria-label="Resume for application"
                    value={resume}
                    onChange={(e) => setResume(e.target.value)}
                  >
                    <option value="">Use my default resume</option>
                    {docs
                      .filter((d) => d.kind === "resume")
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                  </select>
                  <button
                    className="primary launch-button"
                    disabled={!url || busy || !connected}
                    onClick={start}
                  >
                    {busy ? (
                      <LoaderCircle className="spin" size={18} />
                    ) : (
                      <Sparkles size={18} />
                    )}
                    Start application
                    <ArrowRight size={18} />
                  </button>
                  <small>
                    <ShieldCheck size={13} /> Only verified internships. You
                    approve every submission.
                  </small>
                  {config.mock_enabled && (
                    <button
                      className="demo-link"
                      onClick={() =>
                        setUrl("http://127.0.0.1:8001/mock/jobs/demo-1")
                      }
                    >
                      Try the local test portal <ArrowUpRight size={13} />
                    </button>
                  )}
                </div>
                <div className="orbit-decoration" aria-hidden="true">
                  <Zap size={240} fill="currentColor" strokeWidth={0.5} />
                </div>
              </section>
              <div className="stat-grid">
                {[
                  [apps.length, "Total applications", BriefcaseBusiness, "all"],
                  [ongoing, "In progress", LoaderCircle, "progress"],
                  [submitted, "Submitted", Check, "submitted"],
                  [
                    attention,
                    "Need your attention",
                    MessageSquare,
                    "attention",
                  ],
                ].map(([value, label, Icon, key]) => {
                  const I = Icon as typeof Check;
                  return (
                    <div className="stat-card" key={key as string}>
                      <span className={`stat-icon ${key}`}>
                        <I size={18} />
                      </span>
                      <small>{label as string}</small>
                      <strong>
                        {value as number}
                        <span>
                          {key === "attention" && attention
                            ? "Your input makes the difference"
                            : "Your journey, one application at a time"}
                        </span>
                      </strong>
                    </div>
                  );
                })}
              </div>
              <div className="dashboard-lower">
                <section className="card recent-card">
                  <div className="section-heading">
                    <h3>
                      Recent applications <span>{apps.length}</span>
                    </h3>
                    <button onClick={() => setView("history")}>
                      View all
                      <ArrowUpRight size={14} />
                    </button>
                  </div>
                  {recent.length ? (
                    recent.map((a) => (
                      <button
                        className="application-row"
                        key={a.id}
                        onClick={() => openApp(a.id)}
                      >
                        <div className="company-logo">
                          {a.job?.company?.[0] || "↗"}
                        </div>
                        <div>
                          <strong>
                            {a.job?.title || "Verifying internship"}
                          </strong>
                          <small>
                            {a.job?.company || "Application portal"} ·{" "}
                            {a.job?.location || "Checking details"}
                          </small>
                        </div>
                        <Badge status={a.status} />
                        <ChevronRight size={16} />
                      </button>
                    ))
                  ) : (
                    <div className="empty-apps">
                      <div>
                        <BriefcaseBusiness size={24} />
                      </div>
                      <h4>A fresh start, full of potential.</h4>
                      <p>
                        Your next opportunity is a Blink away. Add your profile
                        and start with an internship you’re excited about.
                      </p>
                      <button onClick={() => setView("profile")}>
                        Set up your profile <ArrowRight size={15} />
                      </button>
                    </div>
                  )}
                </section>
                <section className="card readiness">
                  <div className="section-heading">
                    <h3>Your profile, ready to go</h3>
                    <UserRound size={18} />
                  </div>
                  <div className="completion">
                    <strong>
                      {completion}
                      <span>%</span>
                    </strong>
                    <p>
                      less to type on
                      <br />
                      your next application
                    </p>
                  </div>
                  <div className="progress-track">
                    <div style={{ width: `${completion}%` }} />
                  </div>
                  <div className="readiness-items">
                    {[
                      [!!profile.personal.email, "Personal details"],
                      [!!profile.education[0]?.school, "Education"],
                      [
                        docs.some((d) => d.kind === "resume"),
                        "Resume uploaded",
                      ],
                    ].map(([done, label]) => (
                      <div key={label as string}>
                        <span className={done ? "done" : ""}>
                          {done ? <Check size={12} /> : <Plus size={12} />}
                        </span>
                        {label as string}
                      </div>
                    ))}
                  </div>
                  <button
                    className="secondary"
                    onClick={() => setView("profile")}
                  >
                    Complete your profile
                    <ArrowRight size={15} />
                  </button>
                  <small>You can start with an incomplete profile.</small>
                </section>
              </div>
              <div className="footer-note">
                <ShieldCheck size={15} />
                <span>
                  Your documents stay encrypted on this device. AI only receives
                  the context needed to help.
                </span>
                <span>BUILT FOR YOUR NEXT STEP</span>
              </div>
            </>
          )}
          {view === "profile" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">ANSWER ONCE, APPLY REPEATEDLY</div>
                  <h1>
                    Your applicant profile<span>.</span>
                  </h1>
                  <p>
                    One home for your details, documents, and the answers you
                    choose to remember.
                  </p>
                </div>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api("/profile", "PUT", profile);
                      setNotice("Profile saved securely on this device.");
                    })
                  }
                >
                  <Check size={16} />
                  Save profile
                </button>
              </div>
              <div className="profile-progress">
                <span>Profile completion</span>
                <div className="progress-track">
                  <div style={{ width: `${completion}%` }} />
                </div>
                <strong>{completion}%</strong>
              </div>
              <div className="tabs">
                {Object.entries(tabNames).map(([key, name]) => (
                  <button
                    key={key}
                    className={tab === key ? "selected" : ""}
                    onClick={() => setTab(key)}
                  >
                    {name}
                  </button>
                ))}
              </div>
              <section className="card profile-card">
                <div className="section-heading">
                  <div>
                    <h3>{tabNames[tab]}</h3>
                    <p>
                      Every field is optional during onboarding. Save any
                      changes before starting an application.
                    </p>
                  </div>
                </div>
                {["personal", "preferences"].includes(tab) && (
                  <>
                    {tab === "preferences" && (
                      <div className="inline-note">
                        <ShieldCheck size={16} />
                        Employer, date, and location dependent preferences will
                        be asked again for each application when needed.
                        Optional self-identification is never inferred or filled
                        without explicit approval.
                      </div>
                    )}
                    {fieldGrid(tab, profile[tab as "personal" | "preferences"])}
                  </>
                )}
                {["education", "employment", "projects", "skills"].includes(
                  tab,
                ) && (
                  <>
                    {(profile[tab as "education"] as RecordData[]).map(
                      (record, index) => (
                        <div className="record-card" key={index}>
                          <div className="record-heading">
                            <strong>
                              {tabNames[tab]} {index + 1}
                            </strong>
                            <button
                              className="icon-btn"
                              aria-label={`Remove ${tabNames[tab]} ${index + 1}`}
                              onClick={() =>
                                setProfile((p) => ({
                                  ...p,
                                  [tab]: (
                                    p[tab as "education"] as RecordData[]
                                  ).filter((_, i) => i !== index),
                                }))
                              }
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                          {fieldGrid(tab, record, index)}
                        </div>
                      ),
                    )}
                    <button
                      className="secondary add-record"
                      onClick={() =>
                        setProfile((p) => ({
                          ...p,
                          [tab]: [
                            ...(p[tab as "education"] as RecordData[]),
                            {},
                          ],
                        }))
                      }
                    >
                      <Plus size={16} />
                      Add{" "}
                      {tab === "employment"
                        ? "experience"
                        : tab === "skills"
                          ? "skill"
                          : tab === "projects"
                            ? "project or certification"
                            : "education"}
                    </button>
                  </>
                )}
                {tab === "documents" && (
                  <>
                    <div className="document-controls">
                      <label>
                        Document type
                        <select
                          value={kind}
                          onChange={(e) => setKind(e.target.value)}
                        >
                          <option value="resume">Resume</option>
                          <option value="cover_letter">Cover letter</option>
                          <option value="transcript">Transcript</option>
                          <option value="supporting">
                            Supporting document
                          </option>
                        </select>
                      </label>
                      <label className="upload-zone">
                        <Upload size={24} />
                        <strong>Choose a document to upload</strong>
                        <span>
                          PDF or DOCX · Up to 15 MB · Encrypted at rest
                        </span>
                        <input
                          aria-label="Upload document"
                          type="file"
                          accept=".pdf,.docx"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file)
                              run(async () => {
                                const form = new FormData();
                                form.append("file", file);
                                form.append("kind", kind);
                                form.append(
                                  "default",
                                  String(
                                    kind === "resume" &&
                                      !docs.some((d) => d.kind === "resume"),
                                  ),
                                );
                                await api("/documents", "POST", form);
                                setDocs(await api("/documents"));
                                setNotice("Document uploaded and encrypted.");
                              });
                            e.target.value = "";
                          }}
                        />
                      </label>
                    </div>
                    {docs.map((d) => (
                      <div className="document-row" key={d.id}>
                        <div className="file-icon">
                          <FileText size={21} />
                        </div>
                        <div>
                          <strong>{d.name}</strong>
                          <small>
                            {d.kind.replace("_", " ")} ·{" "}
                            {(d.size / 1024).toFixed(1)} KB
                          </small>
                        </div>
                        {d.default ? (
                          <span className="badge success">Default resume</span>
                        ) : (
                          d.kind === "resume" && (
                            <button
                              className="text-button"
                              onClick={() =>
                                run(async () => {
                                  setDocs(
                                    await api(
                                      `/documents/${d.id}/default`,
                                      "PUT",
                                    ),
                                  );
                                })
                              }
                            >
                              Set default
                            </button>
                          )
                        )}
                        <button
                          className="icon-btn"
                          aria-label={`Delete ${d.name}`}
                          onClick={() =>
                            run(async () => {
                              await api(`/documents/${d.id}`, "DELETE");
                              setDocs(await api("/documents"));
                            })
                          }
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                    ))}
                  </>
                )}
                {tab === "memory" && (
                  <>
                    <div className="inline-note">
                      <MessageSquare size={16} />
                      Answers are reused only with your permission.
                      Authorization, sponsorship, dates, and employer details
                      retain their exact wording.
                    </div>
                    {memory.map((m) => (
                      <div className="memory-row" key={m.id}>
                        <div>
                          <strong>{m.question}</strong>
                          <p>{m.answer}</p>
                          <small>
                            Explicitly supplied by you · Approved for reuse
                          </small>
                        </div>
                        <button
                          className="text-button"
                          onClick={() => {
                            setMemEditing(m);
                            setMemQuestion(m.question);
                            setMemAnswer(m.answer);
                            setMemConsent(!!m.sensitive_permission);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="icon-btn"
                          aria-label={`Forget ${m.question}`}
                          onClick={() =>
                            run(async () => {
                              await api(`/memory/${m.id}`, "DELETE");
                              setMemory(await api("/memory"));
                            })
                          }
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                    ))}
                    {!memory.length && (
                      <p className="muted">
                        No remembered answers yet. Save an answer when the agent
                        asks, or add one here.
                      </p>
                    )}
                    <button
                      className="secondary"
                      onClick={() => {
                        setMemEditing({
                          id: "",
                          question: "",
                          answer: "",
                          source: "user",
                        });
                        setMemQuestion("");
                        setMemAnswer("");
                        setMemConsent(false);
                      }}
                    >
                      <Plus size={16} />
                      Add a saved answer
                    </button>
                  </>
                )}
              </section>
            </>
          )}
          {view === "history" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">EVERY STEP, IN ONE PLACE</div>
                  <h1>
                    Your application history<span>.</span>
                  </h1>
                  <p>
                    Track confirmed submissions and pick up applications that
                    need your attention.
                  </p>
                </div>
              </div>
              <div className="search-box">
                <History size={18} />
                <input
                  aria-label="Search applications"
                  placeholder="Search company, position, or status…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <section className="card table-card">
                <table>
                  <thead>
                    <tr>
                      <th>Company & position</th>
                      <th>Started</th>
                      <th>Status</th>
                      <th>Application</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <strong>
                            {a.job?.company || "Application portal"}
                          </strong>
                          <small>{a.job?.title || "Not yet verified"}</small>
                        </td>
                        <td>
                          {new Date(
                            a.submitted_at || a.created_at,
                          ).toLocaleDateString()}
                        </td>
                        <td>
                          <Badge status={a.status} />
                        </td>
                        <td>
                          <a href={a.url} target="_blank" rel="noreferrer">
                            Job posting
                            <ArrowUpRight size={13} />
                          </a>
                        </td>
                        <td>
                          <button
                            className="text-button"
                            onClick={() => openApp(a.id)}
                          >
                            Open
                            <ChevronRight size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!filtered.length && (
                  <div className="empty-apps">
                    <History size={25} />
                    <p>No applications found.</p>
                  </div>
                )}
              </section>
            </>
          )}
          {view === "workspace" && (
            <>
              <div className="workspace-heading">
                <div>
                  <div className="eyebrow">YOUR AGENT, AT WORK</div>
                  <h1>
                    {active?.job?.title || "Agent workspace"}
                    <span>.</span>
                  </h1>
                  <p>
                    {active?.job?.company || "Choose an application to begin"}
                    {active?.job?.location && ` · ${active.job.location}`}
                  </p>
                </div>
                {active && (
                  <div className="workspace-actions">
                    <Badge status={active.status} />
                    {["paused", "manual"].includes(active.status) ? (
                      <button
                        className="secondary"
                        onClick={() => action("continue")}
                        disabled={busy}
                      >
                        <Play size={15} />
                        Continue
                      </button>
                    ) : (
                      ![
                        "cancelled",
                        "rejected",
                        "submitted",
                        "submitting",
                        "submission_unknown",
                      ].includes(active.status) && (
                        <button
                          className="secondary"
                          onClick={() => action("pause")}
                          disabled={busy}
                        >
                          <Pause size={15} />
                          Pause
                        </button>
                      )
                    )}
                    {!["submitted", "cancelled", "rejected"].includes(
                      active.status,
                    ) && (
                      <button
                        className="stop-button"
                        onClick={() => action("stop")}
                      >
                        <Square size={13} />
                        Stop
                      </button>
                    )}
                  </div>
                )}
              </div>
              {!active ? (
                <div className="card empty-apps">
                  <Sparkles size={28} />
                  <h3>Your copilot is ready.</h3>
                  <p>
                    Start an internship application from Overview, or open one
                    from History.
                  </p>
                  <button
                    className="primary"
                    onClick={() => setView("dashboard")}
                  >
                    Start an application
                    <ArrowRight size={16} />
                  </button>
                </div>
              ) : (
                <>
                  {active.error && (
                    <div className="alert error">
                      <CircleHelp size={17} />
                      {active.error}
                    </div>
                  )}
                  <div className="agent-grid">
                    <section className="card browser-panel">
                      <div className="browser-toolbar">
                        <div className="browser-dots">
                          <i />
                          <i />
                          <i />
                        </div>
                        <span>
                          <ShieldCheck size={13} />
                          {active.url}
                        </span>
                        <small>ISOLATED SESSION</small>
                      </div>
                      <div className="browser-image">
                        {image ? (
                          <img
                            src={image}
                            alt="Synchronized preview of the dedicated internship application browser"
                          />
                        ) : (
                          <div className="preview-empty">
                            <Globe2 size={34} />
                            <h3>
                              {active.status === "cancelled"
                                ? "Browser stopped"
                                : "Dedicated browser preview"}
                            </h3>
                            <p>
                              {active.status === "paused"
                                ? "Continue to reconnect and reconstruct the application."
                                : "Screenshots appear as the agent navigates your application."}
                            </p>
                          </div>
                        )}
                      </div>
                      <div className="preview-caption">
                        <span className="online-dot" />
                        Synchronized screenshot preview · Interact manually in
                        the dedicated browser window
                      </div>
                      <div className="agent-progress">
                        {["Verify", "Fill forms", "Your review", "Submit"].map(
                          (step, i) => (
                            <div
                              className={
                                active.status === "submitted" ||
                                (i === 0 && active.job) ||
                                (i === 1 && active.answers?.length) ||
                                (i === 2 &&
                                  ["review", "submitting"].includes(
                                    active.status,
                                  ))
                                  ? "step-complete"
                                  : ""
                              }
                              key={step}
                            >
                              <span>{i + 1}</span>
                              {step}
                            </div>
                          ),
                        )}
                      </div>
                    </section>
                    <section className="card chat-panel">
                      <div className="chat-heading">
                        <span className="agent-avatar">
                          <Zap size={18} />
                        </span>
                        <div>
                          <strong>Blink assistant</strong>
                          <small>
                            {config.ai_enabled
                              ? `AI enabled · ${config.model}`
                              : "Profile & memory assistant"}
                          </small>
                        </div>
                        <span className="online-dot" />
                      </div>
                      <div
                        className="chat-messages"
                        ref={chatScroll}
                        aria-live="polite"
                      >
                        {!active.messages?.length && (
                          <div className="chat-bubble agent">
                            I’m opening your application in a dedicated browser.
                            I’ll check with you whenever I need an answer.
                          </div>
                        )}
                        {active.messages?.map((m) => (
                          <div key={m.id} className={`chat-bubble ${m.role}`}>
                            {m.role === "agent" && (
                              <span className="message-label">
                                <Sparkles size={11} /> ASSISTANT
                              </span>
                            )}
                            {m.message}
                          </div>
                        ))}
                      </div>
                      {active.pending && (
                        <div className="pending-question">
                          <strong>{active.pending.label}</strong>
                          {active.pending.options?.length ? (
                            <select
                              aria-label="Answer option"
                              value={chat}
                              onChange={(e) => setChat(e.target.value)}
                            >
                              <option value="">Choose an answer</option>
                              {active.pending.options.map((o) => (
                                <option key={o}>{o}</option>
                              ))}
                            </select>
                          ) : active.pending.kind === "file" ? (
                            <select
                              aria-label="Document for upload"
                              value={documentChoice}
                              onChange={(e) =>
                                setDocumentChoice(e.target.value)
                              }
                            >
                              <option value="">Choose uploaded document</option>
                              {docs.map((d) => (
                                <option key={d.id} value={d.id}>
                                  {d.name}
                                </option>
                              ))}
                            </select>
                          ) : null}
                          {active.pending.kind !== "verification" &&
                            active.pending.kind !== "file" && (
                              <>
                                <label className="check-label">
                                  <input
                                    type="checkbox"
                                    checked={remember}
                                    onChange={(e) =>
                                      setRemember(e.target.checked)
                                    }
                                  />
                                  Remember this exact answer for future
                                  applications
                                </label>
                                {/gender|race|ethnic|disabilit|veteran/i.test(
                                  active.pending.label,
                                ) && (
                                  <label className="check-label">
                                    <input
                                      type="checkbox"
                                      checked={sensitive}
                                      onChange={(e) =>
                                        setSensitive(e.target.checked)
                                      }
                                    />
                                    I explicitly authorize reuse of this
                                    self-identification answer
                                  </label>
                                )}
                                {["textarea", "text"].includes(
                                  active.pending.kind,
                                ) && (
                                  <button
                                    className="text-button"
                                    onClick={() =>
                                      run(async () => {
                                        const result = await api(
                                          `/applications/${active.id}/draft`,
                                          "POST",
                                        );
                                        setChat(result.draft);
                                        setDraftOrigin(true);
                                        setNotice(
                                          "Draft generated. Review and edit it before sending.",
                                        );
                                      })
                                    }
                                  >
                                    <Sparkles size={13} />
                                    Help draft an answer
                                  </button>
                                )}
                              </>
                            )}
                        </div>
                      )}
                      <div className="chat-input">
                        <textarea
                          aria-label="Message to assistant"
                          placeholder={
                            active.pending
                              ? "Your answer…"
                              : "Ask your agent, or type “pause”…"
                          }
                          value={chat}
                          onChange={(e) => setChat(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              send();
                            }
                          }}
                        />
                        <button
                          aria-label="Send message"
                          disabled={
                            busy ||
                            (!chat && !documentChoice) ||
                            ["submitted", "cancelled", "rejected"].includes(
                              active.status,
                            )
                          }
                          onClick={send}
                        >
                          <Send size={17} />
                        </button>
                      </div>
                      <div className="chat-footnote">
                        <Command size={11} /> Enter to send · Shift + Enter for
                        a new line
                      </div>
                    </section>
                  </div>
                  <section className="card review-card">
                    <div className="section-heading">
                      <div>
                        <h3>
                          {active.status === "review"
                            ? "Ready for your final review"
                            : "Completed answers"}{" "}
                          <span>{active.answers?.length || 0}</span>
                        </h3>
                        <p>
                          Check every answer and uploaded document. Profile
                          facts, your answers, and reviewed drafts are labeled.
                        </p>
                      </div>
                      {active.status === "review" && (
                        <button
                          className="primary"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await api(
                                `/applications/${active.id}/approve`,
                                "POST",
                                { revision: active.revision, approved: true },
                              );
                              setActive(
                                await api(`/applications/${active.id}`),
                              );
                            })
                          }
                        >
                          <ShieldCheck size={16} />
                          Approve & submit
                        </button>
                      )}
                    </div>
                    {active.confirmation && (
                      <div className="inline-note">
                        <Check size={17} />
                        {active.confirmation}
                      </div>
                    )}
                    {active.warnings?.length ? (
                      <div className="inline-note">
                        <CircleHelp size={17} />
                        The browser blocked requests outside this workflow.
                        Check the preview for missing controls.
                      </div>
                    ) : null}
                    <div className="review-doc">
                      <FileText size={17} />
                      <span>
                        Selected resume:{" "}
                        <strong>
                          {docs.find((d) => d.id === active.resume_id)?.name ||
                            "None selected"}
                        </strong>
                      </span>
                      {["paused", "review", "waiting_answer"].includes(
                        active.status,
                      ) && (
                        <select
                          aria-label="Switch application resume"
                          value={active.resume_id || ""}
                          onChange={(e) =>
                            run(async () => {
                              await api(
                                `/applications/${active.id}/resume/${e.target.value}`,
                                "PUT",
                              );
                              setActive(
                                await api(`/applications/${active.id}`),
                              );
                            })
                          }
                        >
                          <option value="">Change resume…</option>
                          {docs
                            .filter((d) => d.kind === "resume")
                            .map((d) => (
                              <option key={d.id} value={d.id}>
                                {d.name}
                              </option>
                            ))}
                        </select>
                      )}
                    </div>
                    <div className="review-answers">
                      {active.answers?.map((a) => (
                        <div
                          className="review-answer"
                          key={`${a.key}:${a.index}`}
                        >
                          <div>
                            <strong>
                              {a.label}
                              {a.group && ` · ${a.group} ${a.index + 1}`}
                            </strong>
                            <p>
                              {a.kind === "file"
                                ? docs.find((d) => d.id === a.document_id)
                                    ?.name || a.answer
                                : a.answer}
                            </p>
                            <small title={a.explanation}>
                              {a.source === "profile"
                                ? "Verified profile"
                                : a.source === "draft"
                                  ? "AI draft · reviewed by you"
                                  : "Supplied by you"}{" "}
                              · {a.explanation}
                            </small>
                          </div>
                          {active.status === "review" && (
                            <button
                              className="text-button"
                              onClick={() => {
                                setEditing(a);
                                setEdited(a.answer);
                                setDocumentChoice(a.document_id || "");
                              }}
                            >
                              Edit
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                    {!active.answers?.length && (
                      <p className="muted">
                        Answers will appear here as each field is completed.
                      </p>
                    )}
                  </section>
                </>
              )}
            </>
          )}
        </main>
      </div>
      {editing && (
        <div className="modal-backdrop">
          <section className="modal">
            <div className="section-heading">
              <h3>Edit application answer</h3>
              <button
                className="icon-btn"
                onClick={() => setEditing(null)}
                aria-label="Close edit"
              >
                <X size={19} />
              </button>
            </div>
            <label>
              {editing.label}
              {editing.kind === "file" ? (
                <select
                  value={documentChoice}
                  onChange={(e) => setDocumentChoice(e.target.value)}
                >
                  {docs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              ) : editing.options.length ? (
                <select
                  value={edited}
                  onChange={(e) => setEdited(e.target.value)}
                >
                  {editing.options.map((o) => (
                    <option key={o}>{o}</option>
                  ))}
                </select>
              ) : (
                <textarea
                  value={edited}
                  onChange={(e) => setEdited(e.target.value)}
                />
              )}
            </label>
            <p>
              The agent will reconstruct the form with this change. You’ll
              review and approve it again.
            </p>
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api(`/applications/${active!.id}/answers`, "PUT", {
                    key: editing.key,
                    answer: edited,
                    group: editing.group,
                    index: editing.index,
                    document_id:
                      editing.kind === "file" ? documentChoice : null,
                  });
                  setEditing(null);
                  setActive(await api(`/applications/${active!.id}`));
                })
              }
            >
              Save & update application
              <ArrowRight size={16} />
            </button>
          </section>
        </div>
      )}
      {memEditing && (
        <div className="modal-backdrop">
          <section className="modal">
            <div className="section-heading">
              <h3>
                {memEditing.id ? "Edit saved answer" : "Remember an answer"}
              </h3>
              <button
                className="icon-btn"
                onClick={() => setMemEditing(null)}
                aria-label="Close memory edit"
              >
                <X size={19} />
              </button>
            </div>
            <label>
              Exact question
              <input
                disabled={!!memEditing.id}
                value={memQuestion}
                onChange={(e) => setMemQuestion(e.target.value)}
              />
            </label>
            <label>
              Your approved answer
              <textarea
                value={memAnswer}
                onChange={(e) => setMemAnswer(e.target.value)}
              />
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={memConsent}
                onChange={(e) => setMemConsent(e.target.checked)}
              />
              Explicit permission to reuse sensitive self-identification (if
              applicable)
            </label>
            <button
              className="primary"
              disabled={busy || !memQuestion || !memAnswer}
              onClick={() =>
                run(async () => {
                  await api(
                    memEditing.id ? `/memory/${memEditing.id}` : "/memory",
                    memEditing.id ? "PUT" : "POST",
                    {
                      question: memQuestion,
                      answer: memAnswer,
                      sensitive_permission: memConsent,
                    },
                  );
                  setMemory(await api("/memory"));
                  setMemEditing(null);
                })
              }
            >
              Save approved answer
              <Check size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
