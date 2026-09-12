import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Sources } from "./pages/Sources";
import { SourceDetail } from "./pages/SourceDetail";
import { Archive } from "./pages/Archive";
import { Events } from "./pages/Events";
import { EventDetail } from "./pages/Event";
import { Entities } from "./pages/Entities";
import { EntityDetail } from "./pages/Entity";

function Protected({ children }: { children: JSX.Element }) {
  const { user, loading, token } = useAuth();
  if (loading && token) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        جارٍ التحميل...
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function RedirectIfAuthed({ children }: { children: JSX.Element }) {
  const { user } = useAuth();
  if (user) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/login"
            element={
              <RedirectIfAuthed>
                <Login />
              </RedirectIfAuthed>
            }
          />
          <Route
            path="/"
            element={
              <Protected>
                <Dashboard />
              </Protected>
            }
          />
          <Route
            path="/sources"
            element={
              <Protected>
                <Sources />
              </Protected>
            }
          />
          <Route
            path="/sources/:id"
            element={
              <Protected>
                <SourceDetail />
              </Protected>
            }
          />
          <Route
            path="/archive"
            element={
              <Protected>
                <Archive />
              </Protected>
            }
          />
          <Route
            path="/events"
            element={
              <Protected>
                <Events />
              </Protected>
            }
          />
          <Route
            path="/events/new"
            element={
              <Protected>
                <EventDetail />
              </Protected>
            }
          />
          <Route
            path="/events/:id"
            element={
              <Protected>
                <EventDetail />
              </Protected>
            }
          />
          <Route
            path="/entities"
            element={
              <Protected>
                <Entities />
              </Protected>
            }
          />
          <Route
            path="/entities/new"
            element={
              <Protected>
                <EntityDetail />
              </Protected>
            }
          />
          <Route
            path="/entities/:id"
            element={
              <Protected>
                <EntityDetail />
              </Protected>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
