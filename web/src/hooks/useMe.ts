import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import type { Me } from '../api/types'

/** The signed-in user, or null when logged out. Cached app-wide. */
export function useMe() {
  const query = useQuery<Me | null>({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.get<Me>('/me')
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null
        throw err
      }
    },
    staleTime: 5 * 60_000,
  })
  return { me: query.data ?? null, isLoading: query.isLoading }
}

export function useLogout() {
  const queryClient = useQueryClient()
  return async () => {
    await api.post('/auth/logout')
    queryClient.setQueryData(['me'], null)
    queryClient.clear()
    window.location.href = '/'
  }
}
