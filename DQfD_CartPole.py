# -*- coding: utf-8 -*
import matplotlib
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import tensorflow as tf
from gym import wrappers
import gym
import numpy as np
import random
from collections import deque
import pickle
from Config import Config, DDQNConfig, DQfDConfig
import functools


def lazy_property(func):
    attribute = '_lazy_' + func.__name__

    @property
    @functools.wraps(func)
    def wrapper(self):
        if not hasattr(self, attribute):
            setattr(self, attribute, func(self))
        return getattr(self, attribute)
    return wrapper


class DQfDDDQN:
    def __init__(self, env, config):
        self.sess = tf.InteractiveSession()
        self.config = config
        # init experience replay
        self.replay_buffer = deque(maxlen=self.config.replay_buffer_size)  # store the item generated from select_network
        self.demo_buffer = deque()  # store the demo data
        # init some parameters
        self.time_step = 0
        self.epsilon = self.config.INITIAL_EPSILON
        self.state_dim = env.observation_space.shape[0]
        self.action_dim = env.action_space.n
        self.demo_mode = self.config.demo_mode

        self.action_batch = tf.placeholder("int32", [None])
        self.y_input = tf.placeholder("float", [None, self.action_dim])
        self.isdemo = tf.placeholder("float", [None])

        self.eval_input = tf.placeholder("float", [None, self.state_dim])
        self.Q_eval
        self.select_input = tf.placeholder("float", [None, self.state_dim])
        self.Q_select

        self.loss
        self.optimize
        self.update_target_network

        self.saver = tf.train.Saver()

        self.sess.run(tf.global_variables_initializer())

        self.save_model()
        self.restore_model()

    # use the expert-demo-data to pretrain
    def pre_train(self):
        print('pre-training ...')
        for i in range(self.config.PRETRAIN_STEPS):
            if i % 200 == 0:
                print i, 'th step of pre-trianing ...'
            self.train_Q_network(pre_train=True)
        self.time_step = 0
        print 'pre-train finish ...'

    # TODO: How to add the variable created in tf.layers.dense to the customed collection？
    # def build_layers(self, state, collections, units_1, units_2, w_i, b_i, regularizer=None):
    #     with tf.variable_scope('dese1'):
    #         dense1 = tf.layers.dense(tf.contrib.layers.flatten(state), activation=tf.nn.relu, units=units_1,
    #                                  kernel_initializer=w_i, bias_initializer=b_i,
    #                                  kernel_regularizer=regularizer, bias_regularizer=regularizer)
    #     with tf.variable_scope('dens2'):
    #         dense2 = tf.layers.dense(dense1, activation=tf.nn.relu, units=units_2,
    #                                  kernel_initializer=w_i, bias_initializer=b_i,
    #                                  kernel_regularizer=regularizer, bias_regularizer=regularizer)
    #     with tf.variable_scope('dene3'):
    #         dense3 = tf.layers.dense(dense2, activation=tf.nn.relu, units=self.action_dim,
    #                                  kernel_initializer=w_i, bias_initializer=b_i,
    #                                  kernel_regularizer=regularizer, bias_regularizer=regularizer)
    #     return dense3

    def build_layers(self, state, c_names, units_1, units_2, w_i, b_i, regularizer=None):
        with tf.variable_scope('l1'):
            w1 = tf.get_variable('w1', [self.state_dim, units_1], initializer=w_i, collections=c_names, regularizer=regularizer)
            b1 = tf.get_variable('b1', [1, units_1], initializer=b_i, collections=c_names, regularizer=regularizer)
            dense1 = tf.nn.relu(tf.matmul(state, w1) + b1)
        with tf.variable_scope('l2'):
            w2 = tf.get_variable('w2', [units_1, units_2], initializer=w_i, collections=c_names, regularizer=regularizer)
            b2 = tf.get_variable('b2', [1, units_2], initializer=b_i, collections=c_names, regularizer=regularizer)
            dense2 = tf.nn.relu(tf.matmul(dense1, w2) + b2)
        with tf.variable_scope('l3'):
            w3 = tf.get_variable('w3', [units_2, self.action_dim], initializer=w_i, collections=c_names, regularizer=regularizer)
            b3 = tf.get_variable('b3', [1, self.action_dim], initializer=b_i, collections=c_names, regularizer=regularizer)
            dense3 = tf.matmul(dense2, w3) + b3
        return dense3

    @lazy_property
    def Q_select(self):
        with tf.variable_scope('select_net'):
            c_names = ['select_net_params', tf.GraphKeys.GLOBAL_VARIABLES]
            w_i = tf.random_uniform_initializer(-0.1, 0.1)
            b_i = tf.constant_initializer(0.1)
            regularizer = tf.contrib.layers.l2_regularizer(scale=0.2)  # 注意：只有select网络有l2正则化
            result = self.build_layers(self.select_input, c_names, 24, 24, w_i, b_i, regularizer)
            return result

    @lazy_property
    def Q_eval(self):
        with tf.variable_scope('eval_net'):
            c_names = ['eval_net_params', tf.GraphKeys.GLOBAL_VARIABLES]
            w_i = tf.random_uniform_initializer(-0.1, 0.1)
            b_i = tf.constant_initializer(0.1)
            result = self.build_layers(self.eval_input, c_names, 24, 24, w_i, b_i)
            return result

    def loss_l(self, ae, a):
        return 0.0 if ae == a else 0.8

    def loss_jeq(self, Q_select):
        jeq = 0.0
        for i in range(self.config.BATCH_SIZE):
            ae = self.action_batch[i]
            max_value = float("-inf")
            for a in range(self.action_dim):
                max_value = tf.maximum(Q_select[i][a] + self.loss_l(ae, a), max_value)
            jeq += self.isdemo[i] * (max_value - Q_select[i][ae])
        return jeq

    @lazy_property
    def loss(self):
        loss_dq = tf.reduce_mean(tf.squared_difference(self.Q_select, self.y_input))
        loss_jeq = self.loss_jeq(self.Q_select)
        loss_l2 = tf.reduce_sum([tf.reduce_mean(reg_l) for reg_l in tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)])
        if self.demo_mode == 'get_demo':
            return loss_dq + self.config.LAMBDA_2 * loss_l2
        if self.demo_mode == 'use_demo':
            return loss_dq + self.config.LAMBDA_1 * loss_jeq + self.config.LAMBDA_2 * loss_l2
        assert False

    @lazy_property
    def optimize(self):
        optimizer = tf.train.AdamOptimizer(self.config.LEARNING_RATE)
        return optimizer.minimize(self.loss)  # optimizer只更新selese_network中的参数

    @lazy_property
    def update_target_network(self):
        select_params = tf.get_collection('select_net_params')
        eval_params = tf.get_collection('eval_net_params')
        return [tf.assign(e, s) for e, s in zip(eval_params, select_params)]

    def save_model(self):
        print("Model saved in : ", self.saver.save(self.sess, self.config.MODEL_PATH))

    def restore_model(self):
        self.saver.restore(self.sess, self.config.MODEL_PATH)
        print("Model restored.")

    def perceive(self, state, action, reward, next_state, done, demo):
        # epsilon是不断变小的，也就是随机性不断变小:开始需要更多的探索，所以动作偏随机，之后需要动作能够有效，因此减少随机。
        self.epsilon = max(self.config.FINAL_EPSILON, self.epsilon * self.config.EPSILIN_DECAY)
        self.replay_buffer.append((state, action, reward, next_state, done, demo))  # 经验池添加

    def train_Q_network(self, pre_train=False):
        if not pre_train and len(self.replay_buffer) < self.config.START_TRAINING:
            return
        self.time_step += 1
        # 经验池随机采样minibatch
        minibatch = []
        if pre_train:
            minibatch = random.sample(self.demo_buffer, self.config.BATCH_SIZE)
        elif self.demo_mode == 'get_demo':
            minibatch = random.sample(self.replay_buffer, self.config.BATCH_SIZE)
        elif self.demo_mode == 'use_demo':
            minibatch = random.sample(self.replay_buffer, self.config.BATCH_SIZE - self.config.demo_num)
            demo_batch = random.sample(self.demo_buffer, self.config.demo_num)
            minibatch.extend(demo_batch)
        else:
            assert(False)

        np.random.shuffle(minibatch)
        state_batch = [data[0] for data in minibatch]
        action_batch = [data[1] for data in minibatch]
        reward_batch = [data[2] for data in minibatch]
        next_state_batch = [data[3] for data in minibatch]
        done = [data[4] for data in minibatch]
        demo_data = [data[5] for data in minibatch]

        # 提供给placeholder，因此需要先计算出
        Q_select = self.Q_select.eval(feed_dict={self.select_input: next_state_batch})
        Q_eval = self.Q_eval.eval(feed_dict={self.eval_input: next_state_batch})

        # convert true to 1, false to 0
        done = np.array(done) + 0

        y_batch = np.zeros((self.config.BATCH_SIZE, self.action_dim))
        for i in range(0, self.config.BATCH_SIZE):
            temp = self.Q_select.eval(feed_dict={self.select_input: state_batch[i].reshape((-1, 4))})[0]
            action = np.argmax(Q_select[i])
            temp[action_batch[i]] = reward_batch[i] + (1 - done[i]) * self.config.GAMMA * Q_eval[i][action]
            y_batch[i] = temp

        # 新产生的样本输入
        self.sess.run(self.optimize, feed_dict={
            self.y_input: y_batch,
            self.select_input: state_batch,
            self.action_batch: action_batch,
            self.isdemo: demo_data
        })
        # 此例中一局步数有限，因此可以外部控制一局结束后update ，此处可以不控制
        # if self.time_step % self.config.UPDATE_TARGET_NET == 0:
        #     self.sess.run(self.update_target_network)

    def egreedy_action(self, state):
        if random.random() <= self.epsilon:
            return random.randint(0, self.action_dim - 1)
        return np.argmax(self.Q_select.eval(feed_dict={self.select_input: [state]})[0])


def map_scores(dqfd_scores=None, ddqn_scores=None, xlabel=None, ylabel=None):
    if dqfd_scores is not None:
        plt.plot(dqfd_scores, 'r')
    if ddqn_scores is not None:
        plt.plot(ddqn_scores, 'b')
    if xlabel is not None:
        plt.xlabel(xlabel)
    if ylabel is not None:
        plt.ylabel(ylabel)
    plt.show()


def run_DDQN(index, env):
    with tf.variable_scope('DDQN_' + str(index)):
        agent = DQfDDDQN(env, DDQNConfig())
    scores = []
    for e in range(Config.episode):
        done = False
        score = 0  # sum of reward in one episode
        state = env.reset()
        while done is False:
            action = agent.egreedy_action(state)  # e-greedy action for train
            next_state, reward, done, _ = env.step(action)
            score += reward
            reward = reward if not done or score == 499 else -100
            agent.perceive(state, action, reward, next_state, done, 0.0)  # 0. means it is not a demo data
            agent.train_Q_network(pre_train=False)
            state = next_state
        if done:
            scores.append(score)
            agent.sess.run(agent.update_target_network)
            print("episode:", e, "  score:", score, "  demo_buffer:", len(agent.demo_buffer),
                  "  memory length:", len(agent.replay_buffer), "  epsilon:", agent.epsilon)
            # if np.mean(scores[-min(10, len(scores)):]) > 490:
            #     break
    return scores


def run_DQfD(index, env):
    with tf.variable_scope('DQfD_' + str(index)):
        agent = DQfDDDQN(env, DQfDConfig())
    with open('/Users/mahailong/DQfD/demo.p', 'rb') as f:
        agent.demo_buffer = pickle.load(f)
    agent.pre_train()  # use the demo data to pre-train network
    scores = []
    for e in range(Config.episode):
        done = False
        score = 0  # sum of reward in one episode
        state = env.reset()
        while done is False:
            action = agent.egreedy_action(state)  # e-greedy action for train
            next_state, reward, done, _ = env.step(action)
            score += reward
            reward = reward if not done or score == 499 else -100
            agent.perceive(state, action, reward, next_state, done, 0.0)
            agent.train_Q_network(pre_train=False)
            state = next_state
        if done:
            scores.append(score)
            agent.sess.run(agent.update_target_network)
            print("episode:", e, "  score:", score, "  memory length:", len(agent.replay_buffer), "  epsilon:",
                  agent.epsilon)
            # if np.mean(scores[-min(10, len(scores)):]) > 495:
            #     break
    return scores


# get expert demo data
def get_demo_data(env):
    # env = wrappers.Monitor(env, '/tmp/CartPole-v0', force=True)
    # agent.restore_model()
    with tf.variable_scope('get_demo_data'):
        agent = DQfDDDQN(env, 'get_demo')
    scores = []
    for e in range(Config.episode):
        done = False
        score = 0  # sum of reward in one episode
        state = env.reset()
        demo = []
        while done is False:
            action = agent.egreedy_action(state)  # e-greedy action for train
            next_state, reward, done, _ = env.step(action)
            score += reward
            reward = reward if not done or score == 499 else -100
            agent.perceive(state, action, reward, next_state, done, 0.0)  # 0. means it is not a demo data
            demo.append((state, action, reward, next_state, done, 1.0))  # record the data that could be expert-data
            # print("len(demo):", len(demo))
            agent.train_Q_network(pre_train=False)
            state = next_state
        if done:
            scores.append(score)
            if score == 500:  # expert demo data
                agent.demo_buffer.extend(demo)
            agent.sess.run(agent.update_target_network)
            print("episode:", e, "  score:", score, "  demo_buffer:", len(agent.demo_buffer),
                  "  memory length:", len(agent.replay_buffer), "  epsilon:", agent.epsilon)
            if len(agent.demo_buffer) >= Config.demo_buffer_size:
                agent.demo_buffer = agent.demo_buffer[:Config.demo_buffer_size]
                break
    # write the demo data to a file
    with open('/Users/mahailong/DQfD/test_demo.p', 'wb') as f:
        pickle.dump(agent.demo_buffer, f, protocol=2)


if __name__ == '__main__':
    env = gym.make(Config.ENV_NAME)
    # env = wrappers.Monitor(env, '/tmp/CartPole-v0', force=True)
    # ------------------------ get demo scores by DDQN -----------------------------
    # get_demo_data(env)
    # --------------------------  get DDQN scores ----------------------------------
    ddqn_sum_scores = np.zeros(Config.episode)
    for i in range(Config.iteration):
        scores = run_DDQN(i, env)
        ddqn_sum_scores = [a + b for a, b in zip(scores, ddqn_sum_scores)]
    ddqn_mean_scores = ddqn_sum_scores / Config.iteration
    with open('/Users/mahailong/DQfD/ddqn_mean_scores.p', 'wb') as f:
        pickle.dump(ddqn_mean_scores, f, protocol=2)
    # ----------------------------- get DQfD scores --------------------------------
    dqfd_sum_scores = np.zeros(Config.episode)
    for i in range(Config.iteration):
        scores = run_DQfD(i, env)
        dqfd_sum_scores = [a + b for a, b in zip(scores, dqfd_sum_scores)]
    dqfd_mean_scores = dqfd_sum_scores / Config.iteration
    with open('/Users/mahailong/DQfD/dqfd_mean_scores.p', 'wb') as f:
        pickle.dump(dqfd_mean_scores, f, protocol=2)

    # map_scores(dqfd_scores=dqfd_mean_scores, ddqn_scores=ddqn_mean_scores, xlabel='Red: dqfd         Blue: ddqn', ylabel='Scores')
    # env.close()
    # gym.upload('/tmp/carpole_DDQN-1', api_key='sk_VcAt0Hh4RBiG2yRePmeaLA')


