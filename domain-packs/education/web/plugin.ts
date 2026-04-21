/**
 * Education domain-pack UI plugin.
 *
 * Registers:
 *  - Vocabulary complexity chat hook (passive, client-side analysis)
 *  - Education-scoped slash commands (/teachers, /join, /students, /assign, /escalations)
 *  - Dashboard tab: Teacher Overview (DA / root)
 *  - Sidebar panel: ClassroomPanel (teacher classroom view)
 */

import type { DomainPlugin, PluginRegistration, SlashCommandDef, DashboardTabDef, SidebarPanelDef, PanelComponentProps } from '@lumina/plugins'
import type { ComponentType } from 'react'
import { createElement } from 'react'
import { analyzeVocabulary, postVocabularyMetric } from './services/vocabularyAnalyzer'
import { ClassroomPanel } from './components/ClassroomPanel'
import { TeacherOverview } from './components/TeacherOverview'

// ── Sidebar panel wrapper ───────────────────────────────

type LegacyProps = { auth: { token: string; userId: string; username: string; role: string }; domainId?: string; domainKey?: string }

function wrapLegacy(
  Comp: ComponentType<LegacyProps>,
): ComponentType<PanelComponentProps> {
  return function LegacyWrapper({ auth, domainId, domainKey }: PanelComponentProps) {
    return createElement(Comp, { auth, domainId, domainKey })
  }
}

// ── Education sidebar panels ────────────────────────────

const EDUCATION_SIDEBAR_PANELS: SidebarPanelDef[] = [
  { name: 'ClassroomPanel', component: wrapLegacy(ClassroomPanel) },
]

// ── Education dashboard tabs ────────────────────────────

const EDUCATION_DASHBOARD_TABS: DashboardTabDef[] = [
  {
    id: 'teacher-overview',
    label: 'Teachers',
    roles: ['root', 'admin'],
    component: TeacherOverview,
    order: 110,
  },
]

// ── Education slash commands ───────────────────────────────

const EDUCATION_COMMANDS: SlashCommandDef[] = [
  {
    name: 'teachers',
    operation: 'list_users',
    description: 'Show available teachers',
    args: [],
    defaultParams: { domain_role: 'teacher', domain_id: 'education' },
    allowedRoles: ['student', 'guardian', 'teaching_assistant', 'teacher', 'domain_authority'],
    domainScope: 'education',
    aliases: ['list_teachers'],
    tier: 'user',
  },
  {
    name: 'join',
    operation: 'request_teacher_assignment',
    description: 'Request assignment to a teacher or teaching assistant',
    args: ['teacher_id'],
    allowedRoles: ['student'],
    domainScope: 'education',
    tier: 'user',
  },
  {
    name: 'students',
    operation: 'list_users',
    description: 'List your students',
    args: [],
    defaultParams: { domain_role: 'student', domain_id: 'education' },
    allowedRoles: ['teaching_assistant', 'teacher', 'domain_authority'],
    domainScope: 'education',
    tier: 'user',
  },
  {
    name: 'assign',
    operation: 'assign_student',
    description: 'Assign a student, TA, guardian, or module(s) — use /assign ta|guardian|module|modules <args>',
    args: ['student_id'],
    allowedRoles: ['student', 'teaching_assistant', 'teacher', 'domain_authority'],
    domainScope: 'education',
    tier: 'user',
    subCommands: {
      module: {
        operation: 'assign_module',
        args: ['user_id', 'module_id'],
      },
      modules: {
        operation: 'assign_modules',
        args: ['target', 'module_ids'],
        joinTrailingArgs: true,
      },
      ta: {
        operation: 'assign_ta',
        args: ['ta_id', 'student_ids'],
        joinTrailingArgs: true,
      },
      guardian: {
        operation: 'assign_guardian',
        args: ['guardian_id', 'student_id'],
      },
      commons: {
        operation: 'assign_commons',
        args: ['teacher_id'],
      },
    },
  },
  {
    name: 'assignmodules',
    operation: 'assign_modules',
    description: 'Assign learning modules to a student, classroom, or self',
    args: ['module_ids', 'target'],
    allowedRoles: ['teacher', 'domain_authority'],
    domainScope: 'education',
    tier: 'user',
  },
  {
    name: 'escalations',
    operation: 'list_escalations',
    description: 'List pending escalations',
    args: [],
    allowedRoles: ['teacher', 'domain_authority'],
    aliases: ['list_escalations'],
    domainScope: 'education',
    tier: 'user',
  },
]

// ── Vocabulary analysis chat hook ──────────────────────────

/** State tracker to avoid re-analyzing the same session. */
let vocabAnalyzed = false

function resetVocabState() {
  vocabAnalyzed = false
}

// ── Plugin definition ──────────────────────────────────────

const educationPlugin: DomainPlugin = {
  id: 'education',

  register(api: PluginRegistration) {
    api.addSlashCommands(EDUCATION_COMMANDS)
    api.addDashboardTabs(EDUCATION_DASHBOARD_TABS)
    api.addSidebarPanels(EDUCATION_SIDEBAR_PANELS)
    api.addRoleEquivalences({
      teacher: 'teacher',
      teaching_assistant: 'teaching_assistant',
    })

    api.addChatHooks([
      {
        id: 'education:vocab-analysis',
        async onMessagesChanged(ctx) {
          if (vocabAnalyzed) return
          const studentMsgs = ctx.messages
            .filter((m) => m.role === 'user')
            .map((m) => m.content)
          if (studentMsgs.length < 10) return
          vocabAnalyzed = true
          const metric = await analyzeVocabulary(studentMsgs)
          if (metric) {
            await postVocabularyMetric(
              ctx.apiBase,
              ctx.auth.token,
              ctx.auth.userId,
              metric,
            )
          }
        },
      },
    ])
  },
}

export default educationPlugin
export { resetVocabState }
