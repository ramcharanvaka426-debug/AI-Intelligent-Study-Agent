import { useEffect, useState } from 'react'
import {
  ArrowDownRight, ArrowUpRight, BookOpen, CalendarDays, Check, CircleHelp,
  Clock3, Download, ExternalLink, FileText, GraduationCap, LayoutDashboard, Lightbulb,
  ListChecks, LoaderCircle, Menu, Moon, Plus, Save, Send, Sparkles, Sun,
  Target, Trash2, Upload, X,
} from 'lucide-react'

const MAX_PDF_SIZE = 50 * 1024 * 1024

const initialDashboard = {
  tasks: [
    { id: 'a', title: 'Review lecture notes', due_date: new Date().toISOString().slice(0, 10), category: 'Biology', completed: 0 },
    { id: 'b', title: 'Finish problem set 4', due_date: new Date(Date.now() + 86400000).toISOString().slice(0, 10), category: 'Calculus', completed: 0 },
    { id: 'c', title: 'Read chapter 8', due_date: new Date(Date.now() + 172800000).toISOString().slice(0, 10), category: 'History', completed: 0 },
  ],
  exams: [
    { id: 1, course: 'Calculus II', title: 'Midterm examination', exam_date: new Date(Date.now() + 6 * 86400000).toISOString().slice(0, 10) },
    { id: 2, course: 'Cell Biology', title: 'Unit assessment', exam_date: new Date(Date.now() + 12 * 86400000).toISOString().slice(0, 10) },
  ],
  scores: [
    { id: 1, course: 'Biology', score: 88, label: 'Cell structure quiz' },
    { id: 2, course: 'Calculus', score: 76, label: 'Integration set' },
    { id: 3, course: 'History', score: 94, label: 'Source analysis' },
  ],
  stats: { total_subjects: 3, tasks_completed: 2, tasks_total: 8, average_score: 86 },
}

const navItems = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'tutor', label: 'AI tutor', icon: Sparkles },
  { id: 'library', label: 'My library', icon: FileText },
  { id: 'planner', label: 'Study planner', icon: ListChecks },
  { id: 'quiz', label: 'Practice quiz', icon: CircleHelp },
]

const tutorSubjects = [
  'General',
  'Biology',
  'Chemistry',
  'Physics',
  'Calculus',
  'Computer Science',
  'Mathematics & Statistics',
  'Economics',
  'Psychology',
  'Literature & English',
  'Environmental Science',
  'Engineering',
]

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, options)
  const result = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(result.detail || 'Something went wrong. Please try again.')
  return result
}

function formatDate(value, options = { month: 'short', day: 'numeric' }) {
  if (!value) return 'No date'
  return new Intl.DateTimeFormat('en', options).format(new Date(`${value}T12:00:00`))
}

function App() {
  const [view, setView] = useState('dashboard')
  const [theme, setTheme] = useState(() => localStorage.getItem('studyroom-theme') || 'light')
  const [dashboard, setDashboard] = useState(initialDashboard)
  const [connectionError, setConnectionError] = useState('')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [tasksExpanded, setTasksExpanded] = useState(false)
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [taskDraft, setTaskDraft] = useState({ title: '', due_date: new Date().toISOString().slice(0, 10), category: 'Study' })
  const [tutorQuestion, setTutorQuestion] = useState('')
  const [tutorCourse, setTutorCourse] = useState('General')
  const [tutorMessages, setTutorMessages] = useState([
    { role: 'assistant', text: 'Hi Alex! What are you working through today? Share a question, a tricky concept, or even a first attempt.' },
  ])
  const [tutorBusy, setTutorBusy] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [summary, setSummary] = useState(null)
  const [summaryView, setSummaryView] = useState('short_summary')
  const [materials, setMaterials] = useState([])
  const [plannerSubjects, setPlannerSubjects] = useState('')
  const [plannerHours, setPlannerHours] = useState(2)
  const [plannerSessions, setPlannerSessions] = useState([])
  const [plannerBusy, setPlannerBusy] = useState(false)
  const [examDraft, setExamDraft] = useState({ course: '', title: '', exam_date: '' })
  const [quizUseNotes, setQuizUseNotes] = useState(false)
  const [quizMaterialId, setQuizMaterialId] = useState('')
  const [quizTopic, setQuizTopic] = useState('Cell biology')
  const [quizCount, setQuizCount] = useState(5)
  const [quiz, setQuiz] = useState(null)
  const [quizBusy, setQuizBusy] = useState(false)
  const [quizAnswers, setQuizAnswers] = useState({})
  const [quizScoreSaved, setQuizScoreSaved] = useState(false)
  const [quizScoreBusy, setQuizScoreBusy] = useState(false)

  async function loadDashboard() {
    try {
      const data = await api('/dashboard')
      setDashboard(data)
      setConnectionError('')
    } catch (error) {
      setConnectionError(error.message === 'Failed to fetch' ? 'API is offline. Start the FastAPI server to sync your workspace.' : error.message)
    }
  }

  async function loadMaterials() {
    try {
      const data = await api('/materials')
      setMaterials(data.materials)
      setQuizMaterialId((current) => current && data.materials.some((item) => String(item.id) === current)
        ? current
        : String(data.materials[0]?.id || ''))
      setConnectionError('')
    } catch (error) {
      setConnectionError(error.message === 'Failed to fetch' ? 'Could not load your study library. Check that the API is running.' : error.message)
    }
  }

  useEffect(() => {
    loadDashboard()
    api('/planner').then((data) => setPlannerSessions(data.sessions)).catch(() => {})
    api('/subjects').then((data) => setPlannerSubjects(data.subjects.join(', '))).catch((error) => setConnectionError(error.message))
    loadMaterials()
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('studyroom-theme', theme)
  }, [theme])

  function navigate(nextView) {
    setView(nextView)
    setMobileNavOpen(false)
    if (nextView === 'dashboard') loadDashboard()
  }

  async function toggleTask(task) {
    const completed = !task.completed
    setDashboard((current) => ({ ...current, tasks: current.tasks.map((item) => item.id === task.id ? { ...item, completed: Number(completed) } : item) }))
    if (typeof task.id === 'number') {
      try {
        await api(`/tasks/${task.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ completed }) })
        loadDashboard()
      } catch (error) {
        setConnectionError(error.message)
        loadDashboard()
      }
    }
  }

  async function addTask(event) {
    event.preventDefault()
    try {
      await api('/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(taskDraft) })
      setTaskDraft({ title: '', due_date: new Date().toISOString().slice(0, 10), category: 'Study' })
      setShowTaskForm(false)
      loadDashboard()
    } catch (error) {
      setConnectionError(error.message)
    }
  }

  async function createExam(event) {
    event.preventDefault()
    try {
      await api('/exams', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(examDraft) })
      setExamDraft({ course: '', title: '', exam_date: '' })
      loadDashboard()
    } catch (error) {
      setConnectionError(error.message)
    }
  }

  async function askTutor(event) {
    event.preventDefault()
    const question = tutorQuestion.trim()
    if (!question || tutorBusy) return
    setTutorMessages((messages) => [...messages, { role: 'user', text: question }])
    setTutorQuestion('')
    setTutorBusy(true)
    try {
      const result = await api('/tutor', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, course: tutorCourse }) })
      setTutorMessages((messages) => [...messages, { role: 'assistant', text: result.answer }])
    } catch (error) {
      setTutorMessages((messages) => [...messages, { role: 'assistant', text: `I couldn't reach the tutor: ${error.message}` }])
    } finally {
      setTutorBusy(false)
    }
  }

  async function uploadPdf(event) {
    const file = event.target.files?.[0]
    if (!file) return
    if (file.size > MAX_PDF_SIZE) {
      setConnectionError('PDFs must be 50 MB or smaller.')
      event.target.value = ''
      return
    }
    const formData = new FormData()
    formData.append('file', file)
    setPdfBusy(true)
    setSummary(null)
    try {
      const uploaded = await api('/summarize', { method: 'POST', body: formData })
      setSummary(uploaded)
      setQuizMaterialId(String(uploaded.material_id))
      setQuizUseNotes(true)
      setSummaryView('short_summary')
      await loadMaterials()
    } catch (error) {
      setConnectionError(error.message)
    } finally {
      setPdfBusy(false)
      event.target.value = ''
    }
  }

  async function deleteMaterial(material) {
    try {
      await api(`/materials/${material.id}`, { method: 'DELETE' })
      const remaining = materials.filter((item) => item.id !== material.id)
      setMaterials(remaining)
      if (quizMaterialId === String(material.id)) setQuizMaterialId(String(remaining[0]?.id || ''))
      if (!remaining.length) setQuizUseNotes(false)
      if (summary?.material_id === material.id) setSummary(null)
      setConnectionError('')
    } catch (error) {
      setConnectionError(error.message)
    }
  }

  async function generatePlanner(event) {
    event.preventDefault()
    setPlannerBusy(true)
    try {
      const result = await api('/planner/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subjects: plannerSubjects.split(',').map((subject) => subject.trim()).filter(Boolean), hours_per_day: Number(plannerHours), exam_date: examDraft.exam_date || null }),
      })
      setPlannerSessions(result.sessions)
      setPlannerSubjects(result.subjects.join(', '))
      await loadDashboard()
    } catch (error) {
      setConnectionError(error.message)
    } finally {
      setPlannerBusy(false)
    }
  }

  async function toggleSession(session) {
    const completed = !session.completed
    setPlannerSessions((items) => items.map((item) => item.id === session.id ? { ...item, completed: Number(completed) } : item))
    try {
      await api(`/planner/${session.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ completed }) })
    } catch (error) {
      setConnectionError(error.message)
      api('/planner').then((data) => setPlannerSessions(data.sessions)).catch(() => {})
    }
  }

  async function generateQuiz(event) {
    event.preventDefault()
    setQuizBusy(true)
    setQuizAnswers({})
    setQuizScoreSaved(false)
    try {
      setQuiz(await api('/quizzes/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic: quizTopic.trim() || null, material_id: quizUseNotes ? Number(quizMaterialId) : null, count: Number(quizCount) }) }))
    } catch (error) {
      setConnectionError(error.message)
    } finally {
      setQuizBusy(false)
    }
  }

  async function saveQuizScore() {
    if (!quiz || quizScoreBusy || quizScoreSaved) return
    const correct = quiz.questions.reduce((total, question, index) => total + (quizAnswers[index] === question.answer ? 1 : 0), 0)
    setQuizScoreBusy(true)
    try {
      await api('/quiz-scores', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic: quiz.topic, correct, total: quiz.questions.length }) })
      setQuizScoreSaved(true)
      loadDashboard()
    } catch (error) {
      setConnectionError(error.message)
    } finally {
      setQuizScoreBusy(false)
    }
  }

  const title = navItems.find((item) => item.id === view)?.label || 'Overview'
  const dateLabel = new Intl.DateTimeFormat('en', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date())

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNavOpen ? 'sidebar-open' : ''}`}>
        <a className="brand" href="#overview" onClick={() => navigate('dashboard')}>
          <span className="brand-mark"><GraduationCap size={21} strokeWidth={2.2} /></span>
          <span>studyroom<span className="brand-period">.</span></span>
        </a>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-link ${view === id ? 'active' : ''}`} onClick={() => navigate(id)}>
              <Icon size={18} strokeWidth={1.9} /><span>{label}</span>
              {id === 'tutor' && <span className="nav-spark"><Sparkles size={13} /></span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="streak-card">
            <div className="streak-icon"><Target size={18} /></div>
            <div><strong>{dashboard.stats?.tasks_completed || 0} tasks complete</strong><span>Across your study plan</span></div>
          </div>
          <div className="profile-button"><span className="avatar">AS</span><span className="profile-copy"><strong>Alex Student</strong><small>My learning space</small></span></div>
        </div>
      </aside>

      {mobileNavOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <main className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{title}</strong></div>
          <div className="topbar-date"><span className="live-dot" />{dateLabel}</div>
          <button className="theme-toggle" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
        </header>
        {connectionError && <div className="connection-banner"><CircleHelp size={16} /><span>{connectionError}</span><button aria-label="Dismiss" onClick={() => setConnectionError('')}><X size={15} /></button></div>}

        {view === 'dashboard' && <DashboardView
          dashboard={dashboard} tasksExpanded={tasksExpanded} setTasksExpanded={setTasksExpanded}
          showTaskForm={showTaskForm} setShowTaskForm={setShowTaskForm} taskDraft={taskDraft}
          setTaskDraft={setTaskDraft} addTask={addTask} toggleTask={toggleTask} navigate={navigate}
        />}
        {view === 'tutor' && <TutorView messages={tutorMessages} question={tutorQuestion} setQuestion={setTutorQuestion} course={tutorCourse} setCourse={setTutorCourse} busy={tutorBusy} onSubmit={askTutor} />}
        {view === 'library' && <LibraryView busy={pdfBusy} materials={materials} onDelete={deleteMaterial} summary={summary} summaryView={summaryView} setSummaryView={setSummaryView} onUpload={uploadPdf} />}
        {view === 'planner' && <PlannerView subjects={plannerSubjects} setSubjects={setPlannerSubjects} hours={plannerHours} setHours={setPlannerHours} exam={examDraft} setExam={setExamDraft} onExamSubmit={createExam} sessions={plannerSessions} busy={plannerBusy} onToggleSession={toggleSession} onSubmit={generatePlanner} />}
        {view === 'quiz' && <QuizView topic={quizTopic} setTopic={setQuizTopic} useNotes={quizUseNotes} setUseNotes={setQuizUseNotes} materials={materials} materialId={quizMaterialId} setMaterialId={setQuizMaterialId} count={quizCount} setCount={setQuizCount} quiz={quiz} answers={quizAnswers} setAnswers={setQuizAnswers} scoreSaved={quizScoreSaved} scoreBusy={quizScoreBusy} onSaveScore={saveQuizScore} busy={quizBusy} onSubmit={generateQuiz} />}
      </main>
    </div>
  )
}

function PageHeading({ eyebrow, title, description, action }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

function DashboardView({ dashboard, tasksExpanded, setTasksExpanded, showTaskForm, setShowTaskForm, taskDraft, setTaskDraft, addTask, toggleTask, navigate }) {
  const tasks = tasksExpanded ? dashboard.tasks : dashboard.tasks.slice(0, 4)
  const completed = dashboard.stats?.tasks_completed || 0
  const total = dashboard.stats?.tasks_total || 0
  return (
    <div className="page-content dashboard-page">
      <PageHeading eyebrow="YOUR STUDY SPACE" title="Good morning, Alex" description="A little progress adds up. Here's your learning at a glance." action={<button className="primary-button" onClick={() => navigate('planner')}><Sparkles size={16} /> Plan my week</button>} />
      <section className="stats-grid" aria-label="Study statistics">
        <StatCard label="Subjects" value={dashboard.stats?.total_subjects || 0} note="Across your study list" icon={BookOpen} tone="blue" trend="In progress" />
        <StatCard label="Tasks completed" value={`${completed}/${total}`} note="Keep your momentum" icon={Check} tone="green" trend={`${total ? Math.round((completed / total) * 100) : 0}%`} />
        <StatCard label="Average score" value={`${dashboard.stats?.average_score || 0}%`} note="Across your recent quizzes" icon={Target} tone="coral" trend="Quiz results" />
        <StatCard label="Next exam" value={dashboard.exams?.[0] ? `${Math.max(0, Math.ceil((new Date(`${dashboard.exams[0].exam_date}T12:00:00`) - new Date()) / 86400000))} days` : '—'} note={dashboard.exams?.[0]?.course || 'Nothing scheduled'} icon={Clock3} tone="gold" trend="View calendar" />
      </section>

      <div className="dashboard-grid">
        <section className="panel tasks-panel">
          <div className="panel-heading"><div><div className="eyebrow">YOUR CHECKLIST</div><h2>Tasks for today</h2></div><button className="small-icon-button" aria-label="Add task" onClick={() => setShowTaskForm(!showTaskForm)}><Plus size={18} /></button></div>
          {showTaskForm && <form className="task-form" onSubmit={addTask}><input aria-label="Task name" placeholder="What needs doing?" value={taskDraft.title} onChange={(event) => setTaskDraft({ ...taskDraft, title: event.target.value })} required minLength={2} /><input aria-label="Due date" type="date" value={taskDraft.due_date} onChange={(event) => setTaskDraft({ ...taskDraft, due_date: event.target.value })} required /><button className="primary-button compact" type="submit">Add task</button></form>}
          <div className="task-list">{tasks.map((task) => <TaskRow key={task.id} task={task} onToggle={toggleTask} />)}</div>
          <button className="text-button view-all" onClick={() => setTasksExpanded(!tasksExpanded)}>{tasksExpanded ? 'Show less' : 'View all tasks'} <ArrowUpRight size={14} /></button>
        </section>

        <section className="panel exams-panel">
          <div className="panel-heading"><div><div className="eyebrow">COMING UP</div><h2>Exam calendar</h2></div><button className="text-button" onClick={() => navigate('planner')}>Study plan <ArrowUpRight size={14} /></button></div>
          <div className="exam-list">{dashboard.exams?.map((exam, index) => <div className="exam-row" key={exam.id}><div className={`exam-date exam-date-${index % 2}`}><strong>{formatDate(exam.exam_date, { day: '2-digit' })}</strong><span>{formatDate(exam.exam_date, { month: 'short' }).toUpperCase()}</span></div><div className="exam-info"><strong>{exam.course}</strong><span>{exam.title}</span></div><span className="exam-dot" /></div>)}</div>
          <button className="calendar-link" onClick={() => navigate('planner')}>Open study planner <ArrowUpRight size={15} /></button>
        </section>

        <section className="panel progress-panel">
          <div className="panel-heading"><div><div className="eyebrow">THE BIG PICTURE</div><h2>Progress by subject</h2></div><button className="more-button" aria-label="Create a practice quiz" title="Create a practice quiz" onClick={() => navigate('quiz')}><ArrowUpRight size={16} /></button></div>
          <div className="progress-list">{(dashboard.scores || []).slice(0, 4).map((score, index) => <div className="progress-item" key={score.id}><div className="progress-label"><span className={`subject-dot subject-dot-${index % 4}`} />{score.course}<strong>{score.score}%</strong></div><div className="progress-track"><span className={`progress-fill progress-fill-${index % 4}`} style={{ width: `${score.score}%` }} /></div></div>)}</div>
          <div className="progress-footer"><span><span className="tiny-dot" />Recent assessment scores</span><button onClick={() => navigate('quiz')}>Practice now <ArrowUpRight size={14} /></button></div>
        </section>

        <section className="focus-card">
          <div className="focus-orbit orbit-one" /><div className="focus-orbit orbit-two" />
          <div className="focus-card-copy"><span className="focus-icon"><Lightbulb size={18} /></span><div className="focus-kicker">A GOOD PLACE TO START</div><h2>Make it make sense.</h2><p>Bring one tricky concept to your AI tutor and work through it, step by step.</p><button className="focus-button" onClick={() => navigate('tutor')}>Ask a question <ArrowUpRight size={15} /></button></div>
          <div className="focus-illustration"><div className="focus-book"><BookOpen size={39} strokeWidth={1.4} /></div><div className="focus-spark spark-a">✳</div><div className="focus-spark spark-b">✦</div><div className="focus-spark spark-c">·</div></div>
        </section>
      </div>
    </div>
  )
}

function StatCard({ label, value, note, icon: Icon, tone, trend }) {
  const isPositive = trend.startsWith('↑')
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><span className={`stat-icon ${tone}`}><Icon size={17} /></span></div><div className="stat-value">{value}</div><div className="stat-bottom"><span>{note}</span><span className={`stat-trend ${isPositive ? 'positive' : ''}`}>{isPositive && <ArrowUpRight size={13} />}{trend}</span></div></div>
}

function TaskRow({ task, onToggle }) {
  const overdue = !task.completed && task.due_date < new Date().toISOString().slice(0, 10)
  return <div className={`task-row ${task.completed ? 'is-complete' : ''}`}><button className="task-check" aria-label={task.completed ? `Mark ${task.title} incomplete` : `Complete ${task.title}`} onClick={() => onToggle(task)}>{task.completed ? <Check size={13} /> : null}</button><div className="task-copy"><strong>{task.title}</strong><span>{task.category}</span></div><span className={`task-due ${overdue ? 'overdue' : ''}`}>{overdue ? 'Overdue' : formatDate(task.due_date)}</span></div>
}

function TutorView({ messages, question, setQuestion, course, setCourse, busy, onSubmit }) {
  return <div className="page-content feature-page"><PageHeading eyebrow="YOUR ON-DEMAND STUDY PARTNER" title="Let's figure it out." description="Ask anything from a quick definition to a full worked problem." />
    <div className="tutor-layout"><section className="tutor-chat panel"><div className="chat-header"><div className="tutor-avatar"><Sparkles size={19} /></div><div><strong>Studyroom tutor</strong><span><span className="live-dot" />Here to help you learn</span></div><label className="course-select"><span>SUBJECT</span><select value={course} onChange={(event) => setCourse(event.target.value)}>{tutorSubjects.map((subject) => <option key={subject} value={subject}>{subject}</option>)}</select></label></div>
      <div className="chat-messages">{messages.map((message, index) => <div className={`chat-message ${message.role}`} key={index}><div className="message-avatar">{message.role === 'assistant' ? <Sparkles size={15} /> : 'AS'}</div><div className="message-body"><span>{message.role === 'assistant' ? 'STUDYROOM TUTOR' : 'YOU'}</span><p>{message.text}</p></div></div>)}{busy && <div className="chat-message assistant"><div className="message-avatar"><Sparkles size={15} /></div><div className="message-body typing"><LoaderCircle size={16} className="spin" />Thinking it through…</div></div>}</div>
      <form className="chat-composer" onSubmit={onSubmit}><textarea rows="2" placeholder="Ask a question or describe what you're stuck on…" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit() } }} /><div className="composer-bottom"><span>Shift + Enter for a new line</span><button type="submit" disabled={busy || !question.trim()} aria-label="Send question"><Send size={17} /></button></div></form>
    </section><aside className="tutor-aside"><div className="aside-note"><span className="note-icon"><Lightbulb size={18} /></span><div className="eyebrow">A TIP FOR BETTER ANSWERS</div><h3>Show your thinking.</h3><p>Include what you tried, where you got stuck, or the exact step that feels confusing.</p></div><div className="suggestion-list"><div className="eyebrow">TRY ASKING</div>{['Explain the chain rule with an example', 'Help me compare mitosis and meiosis', 'How do I analyze a primary source?'].map((prompt) => <button key={prompt} onClick={() => setQuestion(prompt)}>{prompt}<ArrowDownRight size={14} /></button>)}</div></aside></div>
  </div>
}

function LibraryView({ busy, materials, onDelete, summary, summaryView, setSummaryView, onUpload }) {
  function downloadSummary() {
    if (!summary) return
    const blob = new Blob([summary[summaryView]], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${summary.filename.replace(/\.pdf$/i, '')}-${summaryView === 'short_summary' ? 'short' : 'detailed'}-summary.txt`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <div className="page-content feature-page"><PageHeading eyebrow="YOUR STUDY MATERIALS" title="Make more of your notes." description="Drop in a lecture PDF and get a clear, review-ready summary." />
    <div className="library-layout"><label className={`upload-zone ${busy ? 'uploading' : ''}`}><input type="file" accept="application/pdf,.pdf" onChange={onUpload} disabled={busy} /><span className="upload-icon">{busy ? <LoaderCircle size={25} className="spin" /> : <Upload size={24} />}</span><strong>{busy ? 'Reading your document…' : 'Choose a PDF to summarize'}</strong><span>{busy ? 'Extracting text and organizing key ideas' : 'Select a file from your device · PDF up to 50 MB'}</span><span className="upload-browse">Browse files</span></label>
      <div className="library-side"><div className="library-stat"><div className="library-stat-icon"><FileText size={18} /></div><div><strong>Study library</strong><span>Uploaded notes are available for quizzes</span></div></div><div className="library-tip"><div className="eyebrow">HOW IT WORKS</div><p>Text is extracted from your PDF, then organized into a quick overview and the most useful ideas to revisit.</p><div className="privacy-line"><Check size={14} /> Materials stay in your local SQLite database</div></div></div>
    </div>
    <section className="material-library panel">
      <div className="panel-heading"><div><div className="eyebrow">SAVED MATERIALS</div><h2>Your library</h2></div><span className="plan-badge">{materials.length} {materials.length === 1 ? 'FILE' : 'FILES'}</span></div>
      {materials.length ? <div className="material-list">{materials.map((material) => {
        const fileUrl = `/api/materials/${material.id}/file`
        const typeLabel = material.original_available ? 'PDF' : 'Saved notes'
        return <article className="material-row" key={material.id}>
          <div className="material-row-icon"><FileText size={17} /></div>
          <div className="material-row-copy"><strong>{material.filename}</strong><span>{material.page_count} {material.page_count === 1 ? 'page' : 'pages'} · {typeLabel} · Added {formatDate(material.created_at.slice(0, 10))}</span></div>
          <div className="material-actions">
            <a className="material-action" href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open</a>
            <a className="material-action" href={`${fileUrl}?download=true`}><Download size={14} /> Download</a>
            <button className="material-delete" type="button" aria-label={`Delete ${material.filename}`} title="Delete material" onClick={() => onDelete(material)}><Trash2 size={15} /></button>
          </div>
        </article>
      })}</div> : <p className="material-empty">No saved materials yet. Upload a PDF to add your first study resource.</p>}
    </section>
    {summary && <section className="summary-panel panel"><div className="summary-toolbar"><div className="summary-heading"><div className="summary-file-icon"><FileText size={18} /></div><div><div className="eyebrow">DOCUMENT SUMMARY</div><h2>{summary.filename}</h2><span>{summary.pages} {summary.pages === 1 ? 'page' : 'pages'} · Ready to review</span></div></div><button className="secondary-button" onClick={downloadSummary}><Download size={15} /> Download .txt</button></div><div className="summary-tabs" role="tablist" aria-label="Summary length"><button role="tab" aria-selected={summaryView === 'short_summary'} className={summaryView === 'short_summary' ? 'selected' : ''} onClick={() => setSummaryView('short_summary')}>Short summary</button><button role="tab" aria-selected={summaryView === 'detailed_summary'} className={summaryView === 'detailed_summary' ? 'selected' : ''} onClick={() => setSummaryView('detailed_summary')}>Detailed study guide</button></div><div className="summary-content">{summary[summaryView]}</div></section>}
  </div>
}

function PlannerView({ subjects, setSubjects, hours, setHours, exam, setExam, onExamSubmit, sessions, busy, onToggleSession, onSubmit }) {
  const grouped = sessions.reduce((days, session) => { (days[session.study_date] ||= []).push(session); return days }, {})
  const completedSessions = sessions.filter((session) => session.completed).length
  return <div className="page-content feature-page"><PageHeading eyebrow="MAKE SPACE TO LEARN" title="A plan you can keep." description="Build a balanced week around the subjects on your mind." />
    <div className="planner-layout"><div className="planner-left-column"><form className="planner-controls panel" onSubmit={onSubmit}><div className="eyebrow">YOUR STUDY RHYTHM</div><label className="field-label">Subjects to focus on<span>Separate with commas</span><input value={subjects} onChange={(event) => setSubjects(event.target.value)} placeholder="Biology, Calculus, History" required /></label><label className="field-label">Daily study time<select value={hours} onChange={(event) => setHours(event.target.value)}><option value="1">1 hour</option><option value="2">2 hours</option><option value="3">3 hours</option><option value="4">4 hours</option></select></label><label className="field-label">Plan through exam date<input type="date" min={new Date().toISOString().slice(0, 10)} value={exam.exam_date} onChange={(event) => setExam({ ...exam, exam_date: event.target.value })} /></label><div className="planner-note"><Lightbulb size={17} /><span>Short, focused sessions with active recall are easier to stick with than long cram sessions.</span></div><button className="primary-button full-button" type="submit" disabled={busy}>{busy ? <LoaderCircle size={16} className="spin" /> : <Sparkles size={16} />}{busy ? 'Building your week…' : 'Generate my week'}</button></form><form className="exam-entry panel" onSubmit={onExamSubmit}><div className="eyebrow">ADD AN EXAM</div><label className="field-label">Subject<input value={exam.course} onChange={(event) => setExam({ ...exam, course: event.target.value })} placeholder="e.g. Biology" required minLength={2} /></label><label className="field-label">Exam name<input value={exam.title} onChange={(event) => setExam({ ...exam, title: event.target.value })} placeholder="e.g. Final exam" required minLength={2} /></label><label className="field-label">Exam date<input type="date" min={new Date().toISOString().slice(0, 10)} value={exam.exam_date} onChange={(event) => setExam({ ...exam, exam_date: event.target.value })} required /></label><button className="secondary-button full-button" type="submit"><CalendarDays size={15} /> Save exam reminder</button></form></div>
      <section className="week-plan panel"><div className="panel-heading"><div><div className="eyebrow">NEXT {sessions.length || 7} DAYS</div><h2>Your study plan</h2></div><span className="plan-badge">{sessions.length ? `${completedSessions}/${sessions.length} DONE` : 'READY WHEN YOU ARE'}</span></div>{sessions.length ? <div className="schedule-list">{Object.entries(grouped).map(([day, items]) => <div className="schedule-day" key={day}><div className="schedule-date"><strong>{formatDate(day, { weekday: 'short' })}</strong><span>{formatDate(day, { day: '2-digit', month: 'short' })}</span></div><div className="schedule-items">{items.map((item) => <div className={`schedule-item ${item.completed ? 'session-complete' : ''}`} key={item.id || `${day}-${item.subject}`}><button className="session-check" type="button" aria-label={item.completed ? `Mark ${item.subject} session incomplete` : `Complete ${item.subject} session`} onClick={() => onToggleSession(item)}>{item.completed ? <Check size={12} /> : null}</button><span className="schedule-marker" /><div><strong>{item.subject}</strong><span>{item.activity}</span></div><small>{item.duration}</small></div>)}</div></div>)}</div> : <div className="empty-plan"><div className="empty-plan-icon"><Clock3 size={23} /></div><strong>Your week, with room to breathe.</strong><p>Choose your subjects and daily study time. Your plan will balance review and practice across the week.</p></div>}</section>
    </div>
  </div>
}

function QuizView({ topic, setTopic, useNotes, setUseNotes, materials, materialId, setMaterialId, count, setCount, quiz, answers, setAnswers, scoreSaved, scoreBusy, onSaveScore, busy, onSubmit }) {
  const correctCount = quiz ? quiz.questions.reduce((total, question, index) => total + (answers[index] === question.answer ? 1 : 0), 0) : 0
  return <div className="page-content feature-page"><PageHeading eyebrow="PRACTICE THAT STICKS" title="Check what you know." description="Generate a quick quiz, then use each answer to guide your next review." />
    <form className="quiz-generator panel" onSubmit={onSubmit}><div className="quiz-generator-icon"><BookOpen size={20} /></div><label className="field-label">Question source<select value={useNotes ? 'notes' : 'topic'} onChange={(event) => setUseNotes(event.target.value === 'notes')}><option value="topic">A study topic</option><option value="notes" disabled={!materials.length}>Uploaded PDF notes</option></select></label>{useNotes && <label className="field-label">Choose notes<select value={materialId} onChange={(event) => setMaterialId(event.target.value)}>{materials.map((item) => <option value={item.id} key={item.id}>{item.filename} · {item.page_count} {item.page_count === 1 ? 'page' : 'pages'}</option>)}</select></label>}<label className="field-label">{useNotes ? 'Focus area (optional)' : 'What are you studying?'}<input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder={useNotes ? 'e.g. Chapter 4' : 'e.g. Cell biology'} required={!useNotes} minLength={2} /></label><label className="field-label question-count">Questions<select value={count} onChange={(event) => setCount(event.target.value)}><option value="3">3 questions</option><option value="5">5 questions</option><option value="8">8 questions</option><option value="10">10 questions</option></select></label><button className="primary-button" type="submit" disabled={busy || (useNotes && (!materials.length || !materialId))}>{busy ? <LoaderCircle size={16} className="spin" /> : <Sparkles size={16} />}{busy ? 'Making your quiz…' : useNotes ? 'Quiz my notes' : 'Generate quiz'}</button></form>
    {quiz && <div className="quiz-results"><div className="quiz-results-heading"><div><div className="eyebrow">{quiz.material_id ? 'GENERATED FROM YOUR PDF NOTES' : 'YOUR PRACTICE SET'}</div><h2>{quiz.topic}</h2></div><div className="quiz-score-actions"><span className="score-pill">{Object.keys(answers).length ? `${correctCount} / ${quiz.questions.length} correct` : `${quiz.questions.length} questions`}</span>{Object.keys(answers).length === quiz.questions.length && <button className="secondary-button" onClick={onSaveScore} disabled={scoreSaved || scoreBusy}>{scoreBusy ? <LoaderCircle size={14} className="spin" /> : scoreSaved ? <Check size={14} /> : <Save size={14} />}{scoreSaved ? 'Score saved' : scoreBusy ? 'Saving…' : 'Save score'}</button>}</div></div>{quiz.questions.map((question, index) => <section className="question-card panel" key={`${quiz.topic}-${index}`}><div className="question-number">{String(index + 1).padStart(2, '0')}</div><div className="question-content"><h3>{question.question}</h3><div className="answer-options">{question.options.map((option) => { const selected = answers[index] === option; const answered = answers[index] !== undefined; const correct = option === question.answer; return <button type="button" key={option} disabled={scoreSaved} className={`answer-option ${selected ? 'selected' : ''} ${answered && correct ? 'correct' : ''} ${selected && !correct ? 'incorrect' : ''}`} onClick={() => setAnswers((current) => ({ ...current, [index]: option }))}><span className="option-marker">{answered && correct ? <Check size={14} /> : String.fromCharCode(65 + question.options.indexOf(option))}</span>{option}</button> })}</div>{answers[index] !== undefined && <div className={`answer-explanation ${answers[index] === question.answer ? 'right' : 'wrong'}`}><strong>{answers[index] === question.answer ? 'Exactly right.' : 'Not quite.'}</strong> {question.explanation}</div>}</div></section>)}</div>}
    {!quiz && <div className="quiz-empty"><span><Target size={19} /></span><div><strong>Small quizzes make strong memories.</strong><p>Your generated questions will appear here, ready to answer at your own pace.</p></div></div>}
  </div>
}

export default App
