from typing import List, Optional, Dict
from datasets import load_dataset
import pandas as pd
from tqdm import tqdm

from deepeval.dataset import Golden
from deepeval.benchmarks.base_benchmark import DeepEvalBaseBenchmark
from deepeval.models import DeepEvalBaseLLM
from deepeval.benchmarks.bbq.task import BBQTask
from deepeval.benchmarks.bbq.template import BBQTemplate
from deepeval.scorer import Scorer
from deepeval.benchmarks.schema import TrinaryChoiceSchema
from deepeval.telemetry import capture_benchmark_run


class BBQ(DeepEvalBaseBenchmark):
    def __init__(
        self,
        n_shots: int = 5,
        tasks: List[BBQTask] = None,
        **kwargs,
    ):
        assert n_shots <= 5, "BBQ only supports n_shots <= 5"
        super().__init__(**kwargs)
        self.tasks: List[BBQTask] = list(BBQTask) if tasks is None else tasks
        self.n_shots = n_shots
        self.scorer = Scorer()
        self.predictions: Optional[pd.DataFrame] = None
        self.overall_score: Optional[float] = None

    def evaluate(self, model: DeepEvalBaseLLM) -> Dict:
        with capture_benchmark_run("BBQ", len(self.tasks)):
            overall_correct_predictions = 0
            overall_total_predictions = 0
            predictions_row = []
            scores_row = []

            for task in self.tasks:
                goldens = self.load_benchmark_dataset(task)
                task_correct_predictions = 0
                task_total_predictions = len(goldens)
                overall_total_predictions += len(goldens)

                # Calculate task accuracy
                for golden in tqdm(
                    goldens[:20], desc=f"Processing {task.value}"
                ):
                    prediction, score = self.predict(model, golden).values()
                    if score:
                        task_correct_predictions += 1
                        overall_correct_predictions += 1
                    predictions_row.append(
                        (
                            task.value,
                            golden.input,
                            prediction,
                            golden.expected_output,
                            score,
                        )
                    )

                task_accuracy = (
                    task_correct_predictions / task_total_predictions
                )
                print(f"BBQ Task Accuracy (task={task.value}): {task_accuracy}")
                scores_row.append((task.value, task_accuracy))

            # Calculate overall accuracy
            overall_accuracy = (
                overall_correct_predictions / overall_total_predictions
            )
            print(f"Overall BBQ Accuracy: {overall_accuracy}")

            # Create a DataFrame from task_results_data
            # Columns: 'Task', 'Input', 'Prediction', 'Expected Output', 'Score'
            self.predictions = pd.DataFrame(
                predictions_row,
                columns=[
                    "Task",
                    "Input",
                    "Prediction",
                    "Expected Output",
                    "Correct",
                ],
            )
            self.task_scores = pd.DataFrame(
                scores_row, columns=["Task", "Score"]
            )
            self.overall_score = overall_accuracy

            return overall_accuracy

    def predict(self, model: DeepEvalBaseLLM, golden: Golden) -> Dict:
        # Define prompt template
        prompt: dict = BBQTemplate.generate_output(
            input=golden.input,
            n_shots=self.n_shots,
        )

        # Enforced model generation
        try:
            res: TrinaryChoiceSchema = model.generate(
                prompt=prompt, schema=TrinaryChoiceSchema
            )
            prediction = str(res.answer)
        except TypeError:
            prompt += "\n\nOutput only 'A', 'B', or 'C. Full answer not needed."
            prediction = model.generate(prompt)

        # For native models, shouldn't happen but just in case
        if isinstance(prediction, tuple):
            prediction = prediction[0]

        score = self.scorer.exact_match_score(
            golden.expected_output, prediction
        )

        return {"prediction": prediction, "score": score}

    def load_benchmark_dataset(self, task: BBQTask) -> List[Golden]:
        # Load full dataset
        dataset_mapping = {
            BBQTask.AGE: "age_dataset",
            BBQTask.DISABILITY_STATUS: "disability_dataset",
            BBQTask.GENDER_IDENTITY: "gender_identity_dataset",
            BBQTask.NATIONALITY: "nationality_dataset",
            BBQTask.PHYSICAL_APPEARANCE: "physical_appearance_dataset",
            BBQTask.RACE_ETHNICITY: "race_ethnicity_dataset",
            BBQTask.RACE_X_SES: "race_x_ses_dataset",
            BBQTask.RACE_X_GENDER: "race_x_gender_dataset",
            BBQTask.RELIGION: "religion_dataset",
            BBQTask.SES: "ses_dataset",
            BBQTask.SEXUAL_ORIENTATION: "sexual_orientation_dataset",
        }
        dataset_attr = dataset_mapping.get(task)
        if dataset_attr:
            if not hasattr(self, dataset_attr):
                dataset = load_dataset(
                    "heegyu/bbq", task.value, trust_remote_code=True
                )
                setattr(self, dataset_attr, dataset)
            else:
                dataset = getattr(self, dataset_attr)

        # Construct test set
        goldens: List[Golden] = []
        for data in dataset["test"]:
            input = BBQTemplate.format_question(data, False)
            expected_output = BBQTemplate.format_answer(data)
            golden = Golden(input=input, expected_output=expected_output)
            goldens.append(golden)
        return goldens