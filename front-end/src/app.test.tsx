import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import App from '../app'

describe('App', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows consent screen then opens chat interface', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
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
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(screen.getByRole('button', { name: 'I Agree' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'I Agree' }))

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toBeInTheDocument()
    })
  })

  it('shows api error message when chat request fails', async () => {
    const fetchMock = vi
      .fn()
      // Domain info request
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
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
        }),
      })
      // Chat request
      .mockResolvedValueOnce({
        ok: false,
        text: async () => 'api down',
      })

    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
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
