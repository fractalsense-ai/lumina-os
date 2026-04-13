/**
 * Education domain-pack UI plugin.
 *
 * Registers:
 *  - Vocabulary complexity chat hook (passive, client-side analysis)
 *  - Education-scoped slash commands (/teachers, /join, /students, /assign, /escalations)
 */

import type { DomainPlugin, PluginRegistration, SlashCommandDef } from '@lumina/plugins'
import { analyzeVocabulary, postVocabularyMetric } from './services/vocabularyAnalyzer'

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
    description: 'Request assignment to a teacher',
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
    description: 'Assign a student to your roster',
    args: ['student_id'],
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
