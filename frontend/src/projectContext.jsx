import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@clairlabs-ai/prp-ui';
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
    <Select
      value={project?.id != null ? String(project.id) : undefined}
      onValueChange={(id) => {
        const p = projects.find((x) => String(x.id) === id);
        if (p) setActiveProject(p);
      }}
    >
      <SelectTrigger
        aria-label="Active surveillance workspace"
        className="max-w-[min(220px,42vw)]"
        title="Active surveillance workspace — Fetch, Demo, Pathfinder, and KG use this project"
      >
        <SelectValue placeholder="Project" />
      </SelectTrigger>
      <SelectContent>
        {projects.map((p) => (
          <SelectItem key={p.id} value={String(p.id)}>
            {p.name}{(p.post_count ?? 0) === 0 ? ' (empty)' : ''}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
