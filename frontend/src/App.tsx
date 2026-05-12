import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './components/auth/AuthContext';
import { ThemeProvider } from './components/ThemeProvider';
import Login from './components/auth/Login';
import Register from './components/auth/Register';
import Dashboard from './components/auth/Dashboard';
import AudioUpload from './components/AudioUpload';
import ProcessingStatus from './components/ProcessingStatus';
import TranscriptionViewer from './components/TranscriptionViewer';
import './App.css';

// Private route component for protected pages
const PrivateRoute = ({ children }: { children: JSX.Element }) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? children : <Navigate to="/login" replace />;
};

function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
            <Route path="/upload" element={<PrivateRoute><AudioUpload /></PrivateRoute>} />
            <Route path="/transcription/:transcriptionId" element={<PrivateRoute><TranscriptionViewer /></PrivateRoute>} />
            <Route path="/" element={<Navigate to="/login" replace />} />
            {/* Redirect any other routes to login for now */}
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </AuthProvider>
  );
}

export default App;