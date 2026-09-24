import { createContext, useContext } from 'react'

// The logged-in person and a logout function, provided by App.jsx.
export const AuthContext = createContext({ user: null, logout: () => {} })

export function useAuth() {
  return useContext(AuthContext)
}
