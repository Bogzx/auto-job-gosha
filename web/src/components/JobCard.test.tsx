import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Job } from '../api/types'
import { JobCard } from './JobCard'

const JOB: Job = {
  id: 1,
  url: 'https://example.com/job',
  title: 'Python Developer Intern',
  company: 'CodeCorp',
  location: 'Cluj-Napoca, Romania',
  description: 'Write Python all day.',
  salary_min: 1000,
  salary_max: 1500,
  salary_currency: 'EUR',
  source: 'indeed',
  posted_at: null,
  first_seen_at: new Date(Date.now() - 2 * 86400_000).toISOString(),
  match_score: 0.92,
  match_reasons: ['python', 'docker'],
  feedback: null,
  applied: false,
}

describe('JobCard', () => {
  it('renders the key job facts', () => {
    render(<JobCard job={JOB} onSelect={() => undefined} />)
    expect(screen.getByText('Python Developer Intern')).toBeInTheDocument()
    expect(screen.getByText(/CodeCorp/)).toBeInTheDocument()
    expect(screen.getByText('92%')).toBeInTheDocument()
    expect(screen.getByText(/python, docker/)).toBeInTheDocument()
    expect(screen.getByText('Indeed')).toBeInTheDocument()
    expect(screen.getByText(/1k–1.5k EUR|1000–1500 EUR/)).toBeInTheDocument()
    expect(screen.getByText('2d ago')).toBeInTheDocument()
  })

  it('shows the applied marker', () => {
    render(<JobCard job={{ ...JOB, applied: true }} onSelect={() => undefined} />)
    expect(screen.getByText('APPLIED')).toBeInTheDocument()
  })

  it('hides the match badge without a score', () => {
    render(<JobCard job={{ ...JOB, match_score: null }} onSelect={() => undefined} />)
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument()
  })

  it('fires onSelect when clicked', async () => {
    const onSelect = vi.fn()
    render(<JobCard job={JOB} onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button'))
    expect(onSelect).toHaveBeenCalledWith(JOB)
  })
})
