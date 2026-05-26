import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AuthProvider, useAuth } from './components/auth/AuthContext';
import Login from './components/auth/Login';
import Register from './components/auth/Register';
import Dashboard from './components/auth/Dashboard';
import AudioUpload from './components/AudioUpload';
import ProcessingStatus from './components/ProcessingStatus';
import TranscriptionViewer from './components/TranscriptionViewer';
import AdminJobsDashboard from './components/admin/AdminJobsDashboard';
import LandingPage from './components/LandingPage';
import { AppShell, PublicShell } from './components/SiteNav';
import MotionDirector from './components/MotionDirector';
import './App.css';

const PrivateRoute = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <AppShell>{children}</AppShell> : <Navigate to="/login" replace />;
};

const PublicOnlyRoute = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <Navigate to="/dashboard" replace /> : children;
};

const HomeRoute = () => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? (
    <Navigate to="/dashboard" replace />
  ) : (
    <PublicShell>
      <LandingPage />
    </PublicShell>
  );
};

const UnknownRoute = () => {
  const { isAuthenticated } = useAuth();
  return <Navigate to={isAuthenticated ? "/dashboard" : "/login"} replace />;
};

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <MotionDirector />
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/login" element={<PublicOnlyRoute><Login /></PublicOnlyRoute>} />
          <Route path="/register" element={<PublicOnlyRoute><Register /></PublicOnlyRoute>} />
          <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
          <Route path="/upload" element={<PrivateRoute><AudioUpload /></PrivateRoute>} />
          <Route path="/processing/:transcriptionId" element={<PrivateRoute><ProcessingStatus /></PrivateRoute>} />
          <Route path="/transcription/:transcriptionId" element={<PrivateRoute><TranscriptionViewer /></PrivateRoute>} />
          <Route path="/admin/jobs" element={<PrivateRoute><AdminJobsDashboard /></PrivateRoute>} />
          <Route path="*" element={<UnknownRoute />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
