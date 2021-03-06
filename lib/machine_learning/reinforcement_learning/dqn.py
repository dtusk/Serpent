import collections

from lib.input_controller import InputController
from lib.machine_learning.reinforcement_learning.epsilon_greedy_q_policy import EpsilonGreedyQPolicy

from lib.visual_debugger.visual_debugger import VisualDebugger

from keras.models import Sequential
from keras.layers import Dense, Activation, Flatten, Convolution2D
from keras.optimizers import Adam

import numpy as np

import random
import itertools

from termcolor import cprint


class DQN:

    def __init__(
        self,
        input_shape=None,
        input_mapping=None,
        replay_memory_size=15000,
        batch_size=32,
        action_space=None,
        max_steps=1000000,
        observe_steps=None,
        initial_epsilon=1.0,
        final_epsilon=0.1,
        gamma=0.99,
        model_file_path=None,
        model_learning_rate=1e-5,
        override_epsilon=False
    ):
        self.input_shape = input_shape
        self.replay_memory = collections.deque(maxlen=replay_memory_size)
        self.batch_size = batch_size
        self.action_space = action_space
        self.action_count = len(self.action_space.combinations)
        self.action_input_mapping = self._generate_action_space_combination_input_mapping(input_mapping)
        self.frame_stack = None
        self.max_steps = max_steps
        self.observe_steps = observe_steps or (0.1 * replay_memory_size)
        self.current_observe_step = 0
        self.current_step = 0
        self.initial_epsilon = initial_epsilon
        self.final_epsilon = final_epsilon
        self.previous_epsilon = initial_epsilon
        self.epsilon_greedy_q_policy = EpsilonGreedyQPolicy(
            initial_epsilon=self.initial_epsilon,
            final_epsilon=self.final_epsilon,
            max_steps=self.max_steps
        )
        self.gamma = gamma
        self.current_action = None
        self.current_action_index = None
        self.current_action_type = None
        self.first_run = True
        self.mode = "TRAIN"

        self.model_learning_rate = model_learning_rate
        self.model = self._initialize_model(model_learning_rate)

        if model_file_path is not None:
            self.load_model_weights(model_file_path, override_epsilon)

        self.model_loss = 0

        self.visual_debugger = VisualDebugger()

    def enter_train_mode(self):
        if self.previous_epsilon is not None:
            self.epsilon_greedy_q_policy.epsilon = self.previous_epsilon
            self.previous_epsilon = None

        self.mode = "TRAIN"

    def enter_run_mode(self):
        self.previous_epsilon = self.epsilon_greedy_q_policy.epsilon
        self.epsilon_greedy_q_policy.epsilon = 0
        self.mode = "RUN"

    def next_step(self):
        if self.mode == "TRAIN":
            self.current_step += 1
            self.current_observe_step += 1

    def build_frame_stack(self, game_frame):
        frame_stack = np.stack((
            game_frame,
            game_frame,
            game_frame,
            game_frame,
            game_frame,
            game_frame,
            game_frame,
            game_frame
        ), axis=2)

        self.frame_stack = frame_stack.reshape((1,) + frame_stack.shape)

    def update_frame_stack(self, game_frame):
        game_frame = game_frame.reshape((1,) + game_frame.shape + (1,))
        self.frame_stack = np.append(game_frame, self.frame_stack[:, :, :, :-1], axis=3)

    def append_to_replay_memory(self, game_frame, reward):
        previous_frame_stack = self.frame_stack
        self.update_frame_stack(game_frame)

        self.replay_memory.append((
            previous_frame_stack,
            self.current_action_index,
            reward,
            self.frame_stack,
            False
        ))

    def compute_action_type(self):
        use_random = self.epsilon_greedy_q_policy.use_random()
        self.current_action_type = "RANDOM" if use_random else "PREDICTED"

    def erode_epsilon(self, factor=1):
        if self.current_observe_step > self.observe_steps and self.mode == "TRAIN":
            self.epsilon_greedy_q_policy.erode(factor=factor)

    def train_on_mini_batch(self):
        if self.current_observe_step <= self.observe_steps:
            return None

        mini_batch = random.sample(self.replay_memory, self.batch_size)

        inputs = np.zeros((
            self.batch_size,
            self.frame_stack.shape[1],
            self.frame_stack.shape[2],
            self.frame_stack.shape[3]
        ))

        targets = np.zeros((self.batch_size, self.action_count))

        flashback_indices = random.sample(range(self.batch_size), 6)

        for i in range(0, len(mini_batch)):
            if i in flashback_indices:
                flashback_image = np.squeeze(mini_batch[i][3][:, :, :, 1])

                self.visual_debugger.store_image_data(
                    np.array(flashback_image * 255, dtype="uint8"),
                    flashback_image.shape,
                    f"flashback_{flashback_indices.index(i) + 1}"
                )

            previous_frame_stack = mini_batch[i][0]
            action_index = mini_batch[i][1]
            reward = mini_batch[i][2]
            frame_stack = mini_batch[i][3]
            terminal = mini_batch[i][4]

            inputs[i:i + 1] = previous_frame_stack

            targets[i] = self.model.predict(previous_frame_stack)
            projected_future_rewards = self.model.predict(frame_stack)

            if terminal:
                targets[i, action_index] = reward
            else:
                targets[i, action_index] = reward + self.gamma * np.max(projected_future_rewards)
                # Normalize ?

        self.model_loss = self.model.train_on_batch(inputs, targets)

    def generate_action(self):
        self.current_action = self.action_space.combinations[self.current_action_index]

    def get_input_values(self):
        return self.action_input_mapping[self.current_action]

    def save_model_weights(self, file_path_prefix="datasets/model_", is_checkpoint=False):
        epsilon = self.epsilon_greedy_q_policy.epsilon

        if is_checkpoint:
            file_path = f"{file_path_prefix}_dqn_{self.current_step}_{epsilon}_.h5"
        else:
            file_path = f"{file_path_prefix}_dqn_{epsilon}_.h5"

        self.model.save_weights(file_path, overwrite=True)

    def load_model_weights(self, file_path, override_epsilon):
        self.model.load_weights(file_path)
        self.model.compile(loss="mse", optimizer=Adam(lr=self.model_learning_rate))

        *args, steps, epsilon, extension = file_path.split("_")
        self.current_step = int(steps)

        if override_epsilon:
            self.previous_epsilon = float(epsilon)
            self.epsilon_greedy_q_policy.epsilon = float(epsilon)

    def output_step_data(self, reward):
        if self.mode == "TRAIN":
            print(f"CURRENT MODE: {self.mode}")
        else:
            cprint(f"CURRENT MODE: {self.mode}", "grey", "on_yellow", attrs=["dark"])

        print(f"CURRENT STEP: {self.current_step}")

        if self.current_observe_step <= self.observe_steps:
            print(f"CURRENT OBSERVE STEP: {self.current_observe_step}")
            print(f"OBSERVE STEPS: {self.observe_steps}")

        print(f"CURRENT EPSILON: {round(self.epsilon_greedy_q_policy.epsilon, 6)}")
        print(f"CURRENT RANDOM ACTION PROBABILITY: {round(self.epsilon_greedy_q_policy.epsilon * 100.0, 2)}%")
        print(f"ACTION: {[(InputController.human_readable_key_mapping().get(input_value) or input_value).upper() for input_value in self.get_input_values()]}")
        cprint(f"ACTION TYPE: {self.current_action_type}", "white", "on_green" if self.current_action_type == "PREDICTED" else "on_red")
        if reward == 0:
            print(f"REWARD: {reward}")
        else:
            cprint(f"REWARD: {round(reward, 2)}", "white", "on_green" if reward > 0 else "on_red")
        print(f"LOSS: {self.model_loss}")

    def _initialize_model(self, learning_rate):
        model = Sequential()

        model.add(Convolution2D(32, 8, 8, subsample=(4, 4), input_shape=self.input_shape))
        model.add(Activation("relu"))
        model.add(Convolution2D(64, 4, 4, subsample=(2, 2)))
        model.add(Activation("relu"))
        model.add(Convolution2D(64, 3, 3, subsample=(1, 1)))
        model.add(Activation("relu"))
        model.add(Flatten())
        model.add(Dense(512))
        model.add(Activation("relu"))
        model.add(Dense(self.action_count))
        model.add(Activation("linear"))

        adam = Adam(lr=learning_rate)
        model.compile(loss="logcosh", optimizer=adam)

        return model

    def _generate_action_space_combination_input_mapping(self, input_mapping):
        action_input_mapping = dict()

        for combination in self.action_space.combinations:
            combination_values = self.action_space.values_for_combination(combination)
            input_values = [input_mapping[combination_value] for combination_value in combination_values if combination_value is not None]

            action_input_mapping[combination] = list(itertools.chain.from_iterable(input_values))

        return action_input_mapping

















