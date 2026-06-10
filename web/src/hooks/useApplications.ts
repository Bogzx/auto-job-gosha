import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Application, ApplicationStatus } from '../api/types'

export function useApplications() {
  return useQuery({
    queryKey: ['applications'],
    queryFn: () => api.get<{ items: Application[] }>('/applications'),
    select: (data) => data.items,
  })
}

export function useUpdateApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      status,
      notes,
    }: {
      id: number
      status?: ApplicationStatus
      notes?: string
    }) => api.patch<Application>(`/applications/${id}`, { status, notes }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}

export function useDeleteApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/applications/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['applications'] })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}
