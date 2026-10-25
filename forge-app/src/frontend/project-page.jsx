import React, { useState } from 'react';
import ForgeReconciler, {
  Button,
  Heading,
  Label,
  SectionMessage,
  Stack,
  Text,
  TextArea,
  Textfield,
} from '@forge/react';
import { invoke } from '@forge/bridge';

const initialForm = {
  projectKey: '',
  summary: 'Compare GitHub Copilot and Cursor',
  description: 'Research both products for a 50-person engineering team and return pricing, security, sources, and unknowns.',
  budget: '1.00 USD',
  constraints: 'Research only, human approval required',
};

const ProjectPage = () => {
  const [form, setForm] = useState(initialForm);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const update = (field) => (event) => {
    setForm((current) => ({ ...current, [field]: event.target.value }));
  };

  const submit = async () => {
    setBusy(true);
    setResult(null);
    setError('');
    try {
      const response = await invoke('createJiraSpendRequest', form);
      if (response.status !== 'created') {
        setError(response.message || 'Jira did not create the issue.');
      } else {
        setResult(response);
      }
    } catch {
      setError('SpendPilot could not reach Jira. Check the app installation and your project permissions.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack space="space.300">
      <Stack space="space.100">
        <Heading size="xlarge">SpendPilot purchase desk</Heading>
        <Text>Turn a company request into a Jira review issue. This captures the request; it does not approve or purchase anything.</Text>
      </Stack>

      <SectionMessage appearance="information" title="Safe Jira workflow">
        <Text>SpendPilot will create a Task in this project for review. Human approval, vendor selection, and payment remain separate steps.</Text>
      </SectionMessage>

      <Stack space="space.200">
        <Stack space="space.050">
          <Label labelFor="project-key">Jira project key</Label>
          <Textfield id="project-key" name="projectKey" value={form.projectKey} placeholder="Example: SP" onChange={update('projectKey')} />
        </Stack>
        <Stack space="space.050">
          <Label labelFor="summary">Issue summary</Label>
          <Textfield id="summary" name="summary" value={form.summary} onChange={update('summary')} />
        </Stack>
        <Stack space="space.050">
          <Label labelFor="description">Spend request details</Label>
          <TextArea id="description" name="description" value={form.description} minimumRows={4} onChange={update('description')} />
        </Stack>
        <Stack space="space.050">
          <Label labelFor="budget">Maximum budget</Label>
          <Textfield id="budget" name="budget" value={form.budget} onChange={update('budget')} />
        </Stack>
        <Stack space="space.050">
          <Label labelFor="constraints">Constraints</Label>
          <Textfield id="constraints" name="constraints" value={form.constraints} onChange={update('constraints')} />
        </Stack>
        <Button appearance="primary" isDisabled={busy} onClick={submit}>
          {busy ? 'Creating Jira review issue…' : 'Create Jira spend request'}
        </Button>
      </Stack>

      {result ? (
        <SectionMessage appearance="confirmation" title="Jira issue created">
          <Text>SpendPilot created {result.issueKey}. Approval and purchase are still separate.</Text>
        </SectionMessage>
      ) : null}
      {error ? (
        <SectionMessage appearance="error" title="Could not create Jira issue">
          <Text>{error}</Text>
        </SectionMessage>
      ) : null}
    </Stack>
  );
};

ForgeReconciler.render(<ProjectPage />);
