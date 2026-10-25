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
  quantity: 1,
  qualityTarget: 'Return a sourced recommendation for human review.',
};

const initialRequest = 'We need a managed coding assistant for a 50-person engineering team. Compare GitHub Copilot and Cursor, keep the research budget under 1.00 USD, include pricing and security sources, and require human approval before any purchase.';

const ProjectPage = () => {
  const [form, setForm] = useState(initialForm);
  const [naturalLanguageRequest, setNaturalLanguageRequest] = useState(initialRequest);
  const [parseResult, setParseResult] = useState(null);
  const [parsing, setParsing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [existingIssueKey, setExistingIssueKey] = useState('KAN-4');
  const [linking, setLinking] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const update = (field) => (event) => {
    setForm((current) => ({ ...current, [field]: event.target.value }));
  };

  const parseRequest = async () => {
    setParsing(true);
    setParseResult(null);
    setError('');
    try {
      const response = await invoke('parseSpendRequest', { request: naturalLanguageRequest });
      setParseResult(response);
      if (response.isReadyForNextStep && response.parsedTask) {
        const task = response.parsedTask;
        const constraints = [
          ...(task.constraints || []),
          ...(task.merchantOrBrandConstraints || []),
          task.deadline ? `Deadline: ${task.deadline}` : '',
          'Human approval required',
        ].filter(Boolean);
        setForm((current) => ({
          ...current,
          summary: `Research ${task.requestedItemOrService}`,
          description: [
            task.businessPurpose,
            task.expectedDeliverable,
            task.qualityTarget ? `Quality target: ${task.qualityTarget}` : '',
          ].filter(Boolean).join('\n'),
          budget: `${task.budget.amount.toFixed(2)} ${task.budget.currency}`,
          constraints: constraints.join(', '),
          quantity: task.quantity || 1,
          qualityTarget: task.qualityTarget || 'Return a sourced recommendation for human review.',
        }));
      }
    } catch {
      setError('SpendPilot could not reach the OpenAI intake parser. Confirm the encrypted Forge variable and deployment.');
    } finally {
      setParsing(false);
    }
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

  const linkExistingIssue = async () => {
    setLinking(true);
    setResult(null);
    setError('');
    try {
      const response = await invoke('syncJiraSpendRequest', { issueKey: existingIssueKey });
      if (response.status !== 'linked' || !response.backend || response.backend.status === 'unavailable') {
        setError(response.message || 'SpendPilot could not link that Jira issue.');
      } else {
        setResult(response);
      }
    } catch {
      setError('SpendPilot could not read that Jira issue. Check the issue key and app permissions.');
    } finally {
      setLinking(false);
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
        <Stack space="space.100">
          <Heading size="medium">Describe the request naturally</Heading>
          <Text>SpendPilot uses the encrypted OpenAI key to structure the request. The parser is read-only and never authorizes spending.</Text>
        </Stack>
        <TextArea
          id="natural-language-request"
          value={naturalLanguageRequest}
          minimumRows={5}
          onChange={(event) => setNaturalLanguageRequest(event.target.value)}
        />
        <Button appearance="default" isDisabled={parsing || !naturalLanguageRequest.trim()} onClick={parseRequest}>
          {parsing ? 'Parsing request with OpenAI…' : 'Parse request with OpenAI'}
        </Button>
        {parseResult ? (
          <SectionMessage
            appearance={parseResult.isReadyForNextStep ? 'confirmation' : parseResult.status === 'intake_unavailable' ? 'error' : 'warning'}
            title={parseResult.isReadyForNextStep ? 'Request structured' : parseResult.status === 'intake_unavailable' ? 'OpenAI parser unavailable' : 'Clarification needed'}
          >
            {parseResult.isReadyForNextStep ? (
              <Text>OpenAI extracted the request. Review the populated Jira fields below before creating the issue.</Text>
            ) : parseResult.status === 'intake_unavailable' ? (
              <Stack space="space.050">
                <Text>{parseResult.validationErrors?.[0]?.message || 'The OpenAI intake service could not be reached.'}</Text>
                <Text>No Jira issue or spend action was taken.</Text>
              </Stack>
            ) : (
              <Stack space="space.050">
                {(parseResult.clarificationQuestions || ['The request could not be structured safely.']).map((question) => <Text key={question}>{question}</Text>)}
              </Stack>
            )}
          </SectionMessage>
        ) : null}
      </Stack>

      <SectionMessage appearance="information" title="Already have a Jira request?"><Stack space="space.100">
        <Text>Link an existing issue such as KAN-4 to the backend timeline without creating a duplicate Jira issue.</Text>
        <Textfield value={existingIssueKey} onChange={(event) => setExistingIssueKey(event.target.value)} />
        <Button appearance="default" isDisabled={linking || !existingIssueKey.trim()} onClick={linkExistingIssue}>
          {linking ? 'Linking Jira issue…' : 'Link existing issue to backend'}
        </Button>
      </Stack></SectionMessage>

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
          <Stack space="space.050">
            <Text>SpendPilot created {result.issueKey}.</Text>
            {result.backend?.status === 'linked' || result.backend?.status === 'already_linked' ? (
              <Text>Backend task: {result.backend.taskId}. The Jira issue and task timeline are linked. Approval and purchase are still separate.</Text>
            ) : (
              <Text>{result.backend?.message || 'Backend sync is not configured yet. No spend action was taken.'}</Text>
            )}
          </Stack>
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
