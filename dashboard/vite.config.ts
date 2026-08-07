import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Served from https://<user>.github.io/energy_demand_mlops/ (a project
  // repo, not a <user>.github.io repo), so asset URLs need the subpath.
  base: '/energy_demand_mlops/',
})
