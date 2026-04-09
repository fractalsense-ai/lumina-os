import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ActionCard, type ActionCardData } from '../../components/ActionCard'

function makeCard(overrides: Partial<ActionCardData> = {}): ActionCardData {
  return {
    type: 'action_card',
    card_type: 'escalation',
    id: 'esc-001',
    title: 'Escalation Alert',
    body: 'Escalation triggered: frustration_repeated (SLA: 30 min)',
    context: { trigger: 'frustration_repeated', sla_minutes: 30, target_role: 'teacher' },
    actions: [
      { id: 'approve', label: 'Approve', style: 'primary' },
      { id: 'reject', label: 'Reject', style: 'destructive' },
      { id: 'defer', label: 'Defer', style: 'ghost' },
    ],
    resolve_endpoint: '/api/escalations/esc-001/resolve',
    ...overrides,
  }
}

describe('ActionCard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders title and body', () => {
    render(<ActionCard card={makeCard()} token="test-token" />)
    expect(screen.getByText('Escalation Alert')).toBeInTheDocument()
    expect(screen.getByText(/frustration_repeated/)).toBeInTheDocument()
  })

  it('renders all action buttons', () => {
    render(<ActionCard card={makeCard()} token="test-token" />)
    expect(screen.getByRole('button', { name: /Approve/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Reject/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Defer/ })).toBeInTheDocument()
  })

  it('renders SLA info', () => {
    render(<ActionCard card={makeCard()} token="test-token" />)
    const matches = screen.getAllByText(/SLA: 30 min/)
    expect(matches.length).toBeGreaterThanOrEqual(1)
  })

  it('renders command proposal card type', () => {
    const card = makeCard({
      card_type: 'command_proposal',
      title: 'Command Proposal',
      body: 'Admin command: update_physics',
      actions: [
        { id: 'accept', label: 'Accept', style: 'primary' },
        { id: 'reject', label: 'Reject', style: 'destructive' },
        { id: 'modify', label: 'Modify', style: 'outline' },
      ],
    })
    render(<ActionCard card={card} token="test-token" />)
    expect(screen.getByText('Command Proposal')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Accept/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Modify/ })).toBeInTheDocument()
  })

  it('calls resolve endpoint on action click', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    render(<ActionCard card={makeCard()} token="my-token" />)
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/escalations/esc-001/resolve'),
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer my-token',
          }),
        }),
      )
    })
  })

  it('shows resolved state after successful action', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    render(<ActionCard card={makeCard()} token="my-token" />)
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))

    await waitFor(() => {
      expect(screen.getByText('Resolved')).toBeInTheDocument()
    })
  })

  it('shows error on failed resolve', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Not authorized' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ActionCard card={makeCard()} token="my-token" />)
    fireEvent.click(screen.getByRole('button', { name: /Reject/ }))

    await waitFor(() => {
      expect(screen.getByText('Not authorized')).toBeInTheDocument()
    })
  })
})
