import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { api, getProjectId, setProjectId } from './api';

const ProjectContext = createContext({
  project: null,
  projects: [],
  setActiveProject: () => {},
  reload: () => {},
});

export function useProject() {
  return useContext(ProjectContext);
}

export function ProjectProvider({ children }) {
  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState(null);

  const reload = useCallback(async () => {
    try {
      const list = await api.projects();
      setProjects(list);
      const saved = getProjectId();
      const active = list.find((p) => String(p.id) === saved) || list[0];
      if (active) {
        setProjectId(active.id);
        setProject(active);
      }
    } catch {
      setProjects([]);
      setProject(null);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const setActiveProject = (p) => {
    if (!p) return;
    setProjectId(p.id);
    setProject(p);
  };

  return (
    <ProjectContext.Provider value={{ project, projects, setActiveProject, reload }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function ProjectSelector() {
  const { project, projects, setActiveProject } = useProject();
  if (!projects.length) return null;
  return (
    <select
      value={project?.id || ''}
      onChange={(e) => {
        const p = projects.find((x) => String(x.id) === e.target.value);
        if (p) setActiveProject(p);
      }}
      className="text-xs rounded-lg border border-[var(--app-border)] bg-[var(--app-surface)] text-[var(--app-text-secondary)] px-2 py-1.5 max-w-[min(220px,42vw)] truncate"
      title="Active surveillance workspace — Fetch, Demo, Pathfinder, and KG use this project"
    >
      {projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}{(p.post_count ?? 0) === 0 ? ' (empty)' : ''}
        </option>
      ))}
    </select>
  );
}
