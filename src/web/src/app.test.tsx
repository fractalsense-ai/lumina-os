import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import App from '../app'

const DOMAIN_INFO_RESPONSE = {
  domain_id: 'domain/edu/algebra-level-1/v1',
  domain_version: '1.0.0',
  ui_manifest: {
    title: 'Lumina Test Domain',
    subtitle: 'Test subtitle',
    domain_label: 'Education',
    consent_heading: 'Consent Heading',
    consent_text: 'Consent text',
    consent_button_label: 'I Agree',
    placeholder_text: 'Type your message...',
  },
}

const AUTH_STATE = {
  token: 'test-token',
  userId: 'user1',
  username: 'testuser',
  role: 'student',
}

/** Route-aware fetch mock — resolves based on URL rather than call order. */
function makeFetchMock(overrides?: Record<string, () => Promise<unknown>>) {
  const routes: Record<string, () => Promise<unknown>> = {
    '/api/auth/me': () => Promise.resolve({ ok: true }),
    '/api/domain-info': () =>
      Promise.resolve({ ok: true, json: async () => DOMAIN_INFO_RESPONSE }),
    '/api/consent/accept': () => Promise.resolve({ ok: true }),
    ...overrides,
  }

  return vi.fn().mockImplementation((url: string) => {
    for (const [path, handler] of Object.entries(routes)) {
      if (url.includes(path)) return handler()
    }
    return Promise.resolve({ ok: false, text: async () => 'unmocked route' })
  })
}

describe('App', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows consent screen then opens chat interface', async () => {
    window.localStorage.setItem('lumina.auth', JSON.stringify(AUTH_STATE))
    vi.stubGlobal('fetch', makeFetchMock())

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'I Agree' })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'I Agree' }))

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toBeInTheDocument()
    })
  })

  it('shows api error message when chat request fails', async () => {
    window.localStorage.setItem('lumina.auth', JSON.stringify(AUTH_STATE))
    vi.stubGlobal(
      'fetch',
      makeFetchMock({
        '/api/chat': () =>
          Promise.resolve({ ok: false, text: async () => 'api down' }),
      }),
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'I Agree' })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'I Agree' }))

    const input = await screen.findByRole('textbox')
    fireEvent.change(input, { target: { value: 'hello' } })
    fireEvent.click(screen.getByRole('button', { name: '' }))

    await waitFor(() => {
      expect(
        screen.getByText(/Sorry, the API request failed/i),
      ).toBeInTheDocument()
    })
  })
})
