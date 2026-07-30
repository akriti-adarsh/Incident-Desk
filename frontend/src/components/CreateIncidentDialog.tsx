import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { z } from 'zod'

import type { Severity } from '../api/types'
import { useCreateIncident, useServices } from '../api/queries'
import { ApiError } from '../api/client'
import { SEVERITY_LABEL } from '../lib/format'
import { toast } from '../store/ui'
import { Button, Field } from './ui'
import { Modal } from './Modal'

const schema = z.object({
  service_id: z.string().min(1, 'Choose a service'),
  title: z.string().min(1, 'Give the incident a title').max(300),
  severity: z.enum(['sev1', 'sev2', 'sev3', 'sev4']),
  description: z.string().max(20000).optional(),
})

const SEVERITIES: Severity[] = ['sev1', 'sev2', 'sev3', 'sev4']

export function CreateIncidentDialog({ org, onClose }: { org: string; onClose: () => void }) {
  const navigate = useNavigate()
  const services = useServices(org)
  const create = useCreateIncident(org)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { severity: 'sev3' },
  })

  const onSubmit = handleSubmit(async (values) => {
    try {
      const res = await create.mutateAsync(values)
      toast('success', `Incident ${res.data.number} reported`)
      onClose()
      navigate(`/o/${org}/incidents/${res.data.id}`)
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not report the incident.')
    }
  })

  return (
    <Modal title="Report an incident" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <Field label="Service" htmlFor="service" error={errors.service_id?.message}>
          <select id="service" {...register('service_id')}>
            <option value="">Choose a service…</option>
            {(services.data?.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Title" htmlFor="title" error={errors.title?.message}>
          <input id="title" {...register('title')} autoFocus />
        </Field>
        <Field label="Severity" htmlFor="severity" error={errors.severity?.message}>
          <select id="severity" {...register('severity')}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABEL[s]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Description" htmlFor="description" error={errors.description?.message}>
          <textarea id="description" {...register('description')} placeholder="What is happening? Markdown is supported." />
        </Field>
        <div className="modal-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={isSubmitting}>
            Report incident
          </Button>
        </div>
      </form>
    </Modal>
  )
}
