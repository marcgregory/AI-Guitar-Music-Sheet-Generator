import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AuthProvider, useAuth } from './components/auth/AuthContext';
import Login from './components/auth/Login';
import Register from './components/auth/Register';
import Dashboard from './components/auth/Dashboard';
import AudioUpload from './components/AudioUpload';
import ProcessingStatus from './components/ProcessingStatus';
import TranscriptionViewer from './components/TranscriptionViewer';
import LandingPage from './components/LandingPage';
import { AppShell, PublicShell } from './components/SiteNav';
import MotionDirector from './components/MotionDirector';
import './App.css';

// Private route component for protected pages
const PrivateRoute = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <AppShell>{children}</AppShell> : <Navigate to="/login" replace />;
};

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <MotionDirector />
        <Routes>
          <Route path="/" element={<PublicShell><LandingPage /></PublicShell>} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
          <Route path="/upload" element={<PrivateRoute><AudioUpload /></PrivateRoute>} />
          <Route path="/processing/:transcriptionId" element={<PrivateRoute><ProcessingStatus /></PrivateRoute>} />
          <Route path="/transcription/:transcriptionId" element={<PrivateRoute><TranscriptionViewer /></PrivateRoute>} />
          {/* Redirect any other routes to login for now */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
