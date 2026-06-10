import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Subscription, SubscriptionInput } from '../api/types'

export function useSubscriptions() {
  return useQuery({
    queryKey: ['subscriptions'],
    queryFn: () => api.get<{ items: Subscription[] }>('/subscriptions'),
    select: (data) => data.items,
  })
}

export function useMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: () =>
      api.get<{
        smart_keywords: string[]
        locations: string[]
        experience_levels: string[]
        sources: string[]
      }>('/meta'),
    staleTime: Infinity,
  })
}

function useInvalidate() {
  const queryClient = useQueryClient()
  return () => void queryClient.invalidateQueries({ queryKey: ['subscriptions'] })
}

export function useCreateSubscription() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (input: SubscriptionInput) =>
      api.post<Subscription>('/subscriptions', input),
    onSuccess: invalidate,
  })
}

export function useUpdateSubscription() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...input }: Partial<SubscriptionInput> & { id: number }) =>
      api.patch<Subscription>(`/subscriptions/${id}`, input),
    onSuccess: invalidate,
  })
}

export function useToggleSubscription() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api.post<Subscription>(`/subscriptions/${id}/${active ? 'resume' : 'pause'}`),
    onSuccess: invalidate,
  })
}

export function useDeleteSubscription() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/subscriptions/${id}`),
    onSuccess: invalidate,
  })
}
