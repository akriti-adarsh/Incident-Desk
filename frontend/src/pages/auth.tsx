// All authentication screens. They share an AuthShell and talk to the API
// client directly (they run before a session exists). Copy follows the brief:
// active voice, sentence case, errors say what to do and never apologise.

import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { z } from 'zod'

import { ApiError, request } from '../api/client'
import type { Data, LoginResult, TokenPair, User } from '../api/types'
import { Button, Field } from '../components/ui'
import { useAuth } from '../store/auth'
import { toast } from '../store/ui'
import './auth.css'

function AuthShell({ title, subtitle, children }: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <span aria-hidden>▚</span> incident-desk
        </div>
        <h1 className="auth-title">{title}</h1>
        {subtitle ? <p className="auth-subtitle">{subtitle}</p> : null}
        {children}
      </div>
    </div>
  )
}

function apiMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

const PASSWORD_RULE = z
  .string()
  .min(10, 'Use at least 10 characters')
  .refine((v) => /[a-zA-Z]/.test(v), 'Include a letter')
  .refine((v) => /[^a-zA-Z]/.test(v), 'Include a digit or symbol')

// Login (with the MFA challenge step folded in)

const loginSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Enter your password'),
})

export function LoginPage() {
  const navigate = useNavigate()
  const applyTokens = useAuth((s) => s.applyTokens)
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) })

  async function finish(tokens: TokenPair) {
    await applyTokens(tokens)
    const { orgs, activeOrgSlug } = useAuth.getState()
    navigate(activeOrgSlug ? `/o/${activeOrgSlug}/incidents` : '/onboarding')
    if (!orgs.length) navigate('/onboarding')
  }

  const onSubmit = handleSubmit(async (values) => {
    try {
      const res = await request<Data<LoginResult>>('/api/v1/auth/login', {
        method: 'POST',
        body: values,
      })
      if ('mfa_required' in res.data) {
        setMfaToken(res.data.mfa_token)
      } else {
        await finish(res.data)
      }
    } catch (err) {
      toast('error', apiMessage(err, 'Login failed. Check your email and password.'))
    }
  })

  async function submitMfa(e: React.FormEvent) {
    e.preventDefault()
    try {
      const res = await request<Data<TokenPair>>('/api/v1/auth/mfa/challenge', {
        method: 'POST',
        body: { mfa_token: mfaToken, code: mfaCode },
      })
      await finish(res.data)
    } catch (err) {
      toast('error', apiMessage(err, 'That code is not valid. Try again.'))
    }
  }

  if (mfaToken) {
    return (
      <AuthShell title="Enter your code" subtitle="Open your authenticator app and enter the 6-digit code.">
        <form onSubmit={submitMfa}>
          <Field label="Authentication code" htmlFor="mfa-code">
            <input
              id="mfa-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value)}
              autoFocus
            />
          </Field>
          <Button type="submit" variant="primary" style={{ width: '100%' }}>
            Verify and sign in
          </Button>
        </form>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Sign in" subtitle="Welcome back.">
      <form onSubmit={onSubmit}>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <input id="email" type="email" autoComplete="username" {...register('email')} autoFocus />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <input id="password" type="password" autoComplete="current-password" {...register('password')} />
        </Field>
        <Button type="submit" variant="primary" loading={isSubmitting} style={{ width: '100%' }}>
          Sign in
        </Button>
      </form>
      <div className="auth-links">
        <Link to="/forgot-password">Forgot your password?</Link>
        <Link to="/register">Create an account</Link>
      </div>
    </AuthShell>
  )
}

// Register

const registerSchema = z.object({
  full_name: z.string().min(1, 'Enter your name'),
  email: z.string().email('Enter a valid email'),
  password: PASSWORD_RULE,
})

export function RegisterPage() {
  const [done, setDone] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema) })

  const onSubmit = handleSubmit(async (values) => {
    try {
      await request('/api/v1/auth/register', { method: 'POST', body: values })
      setDone(values.email)
    } catch (err) {
      toast('error', apiMessage(err, 'Could not create the account.'))
    }
  })

  if (done) {
    return (
      <AuthShell title="Check your email" subtitle={`We sent a verification link to ${done}. Open it to activate your account.`}>
        <p className="auth-note">The link is valid for 24 hours. In development, find it in Mailpit at http://localhost:58026.</p>
        <Link to="/login" className="auth-back">
          Back to sign in
        </Link>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Create your account">
      <form onSubmit={onSubmit}>
        <Field label="Full name" htmlFor="full_name" error={errors.full_name?.message}>
          <input id="full_name" autoComplete="name" {...register('full_name')} autoFocus />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <input id="email" type="email" autoComplete="username" {...register('email')} />
        </Field>
        <Field
          label="Password"
          htmlFor="password"
          error={errors.password?.message}
          hint="At least 10 characters, with letters and a digit or symbol."
        >
          <input id="password" type="password" autoComplete="new-password" {...register('password')} />
        </Field>
        <Button type="submit" variant="primary" loading={isSubmitting} style={{ width: '100%' }}>
          Create account
        </Button>
      </form>
      <div className="auth-links">
        <Link to="/login">Already have an account? Sign in</Link>
      </div>
    </AuthShell>
  )
}

// Email verification (opened from the emailed link)

export function VerifyEmailPage() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [state, setState] = useState<'idle' | 'ok' | 'error'>('idle')

  async function verify() {
    try {
      await request<Data<User>>('/api/v1/auth/verify-email', {
        method: 'POST',
        body: { token },
      })
      setState('ok')
    } catch {
      setState('error')
    }
  }

  return (
    <AuthShell title="Verify your email">
      {state === 'idle' && (
        <>
          <p className="auth-note">Confirm this is your address to finish setting up your account.</p>
          <Button variant="primary" onClick={verify} disabled={!token} style={{ width: '100%' }}>
            Verify email
          </Button>
        </>
      )}
      {state === 'ok' && (
        <>
          <p className="auth-note">Your email is verified. You can sign in now.</p>
          <Link to="/login" className="auth-back">
            Go to sign in
          </Link>
        </>
      )}
      {state === 'error' && (
        <>
          <p className="auth-error">That link is invalid or has expired. Request a new one from the sign-in page.</p>
          <Link to="/login" className="auth-back">
            Back to sign in
          </Link>
        </>
      )}
    </AuthShell>
  )
}

// Forgot / reset password

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false)
  const [email, setEmail] = useState('')
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await request('/api/v1/auth/forgot-password', { method: 'POST', body: { email } })
    } finally {
      setSent(true)
    }
  }
  return (
    <AuthShell title="Reset your password" subtitle="Enter your email and we will send a reset link.">
      {sent ? (
        <>
          <p className="auth-note">If an account exists for {email}, a reset link is on its way. The link is valid for 30 minutes.</p>
          <Link to="/login" className="auth-back">
            Back to sign in
          </Link>
        </>
      ) : (
        <form onSubmit={submit}>
          <Field label="Email" htmlFor="email">
            <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </Field>
          <Button type="submit" variant="primary" style={{ width: '100%' }}>
            Send reset link
          </Button>
        </form>
      )}
    </AuthShell>
  )
}

const resetSchema = z.object({ password: PASSWORD_RULE })

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token')
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema) })

  const onSubmit = handleSubmit(async ({ password }) => {
    try {
      await request('/api/v1/auth/reset-password', {
        method: 'POST',
        body: { token, password },
      })
      toast('success', 'Password changed. Sign in with your new password.')
      navigate('/login')
    } catch (err) {
      toast('error', apiMessage(err, 'That reset link is invalid or has expired.'))
    }
  })

  return (
    <AuthShell title="Choose a new password">
      <form onSubmit={onSubmit}>
        <Field
          label="New password"
          htmlFor="password"
          error={errors.password?.message}
          hint="At least 10 characters, with letters and a digit or symbol."
        >
          <input id="password" type="password" autoComplete="new-password" {...register('password')} autoFocus />
        </Field>
        <Button type="submit" variant="primary" loading={isSubmitting} disabled={!token} style={{ width: '100%' }}>
          Change password
        </Button>
      </form>
    </AuthShell>
  )
}
