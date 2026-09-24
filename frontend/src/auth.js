import { createContext, useContext } from 'react'

// The logged-in person, a logout function, and refreshUser() to re-read the
// person from the server (e.g. after an admin changes their own name or role).
// Provided by App.jsx.
export const AuthContext = createContext({ user: null, logout: () => {}, refreshUser: async () => {} })

export function useAuth() {
  return useContext(AuthContext)
}
