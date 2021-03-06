import tensorflow as tf
import numpy as np
import matplotlib.pyplot as plt
import time, datetime
from tensorflow.examples.tutorials.mnist import input_data
# 최신 Windows Laptop에서만 사용할것.CPU Version이 높을때 사용.
# AVX를 지원하는 CPU는 Giuthub: How to compile tensorflow using SSE4.1, SSE4.2, and AVX. 
# Ubuntu와 MacOS는 지원하지만 Windows는 없었음. 2018-09-29
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Compuntational Graph Initialization
from tensorflow.python.framework import ops
ops.reset_default_graph()

tf.set_random_seed(777)  # reproducibility

DATA_DIR = "/tmp/ML/MNIST_data"
mnist = input_data.read_data_sets(DATA_DIR, one_hot=True)

# hyper parameters
Alpha_Lr   = 0.001
N_EPISODES = 10
batch_size = 100

# dropout (keep_prob) rate  0.7~0.5 on training, but should be 1 for testing
dropout_rate = tf.placeholder(tf.float32)

def preproc(x):
    # x = x*2 - 1.0
    # per-example mean subtraction (http://ufldl.stanford.edu/wiki/index.php/Data_Preprocessing)
    mean = tf.reduce_mean(x, axis=1, keep_dims=True)
    return x - mean

class Model:
    
    def residual_block(self, x, output_channel, downsampling=False, name='res_block'):
        input_channel = int(x.shape[-1]) # get # of input channels

        if downsampling:
            stride = 2
        else:
            stride = 1

        with tf.variable_scope(name):
            with tf.variable_scope('conv1_in_block'):
                h1 = tf.layers.conv2d(x, output_channel, [3,3], strides=stride, padding='SAME', use_bias=False,
                                      kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=self.seed))
                h1 = tf.layers.batch_normalization(h1, training=self.training)
                h1 = tf.nn.relu(h1)
            
            with tf.variable_scope('conv2_in_block'):
                h2 = tf.layers.conv2d(h1, output_channel, [3,3], strides=1, padding='SAME', use_bias=False,
                                      kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=self.seed))
                h2 = tf.layers.batch_normalization(h2, training=self.training)
            
            # option A - zero padding for extra dimension => no need extra params
            # if downsampling:
            #     pooled_x = tf.layers.average_pooling2d(x, pool_size=2, strides=2, padding='valid')
            #     padded_x = tf.pad(pooled_x, [[0,0], [0,0], [0,0], [input_channel // 2, input_channel // 2]])
            # else:
            #     padded_x = x

            # option B - projection with 1x1 strided conv
            if downsampling:
                x = tf.layers.conv2d(x, output_channel, [1,1], strides=stride, padding='SAME', 
                    kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=self.seed))

            return tf.nn.relu(h2 + x)

    def __init__(self, sess, name):
        self.sess = sess
        self.name = name
        self._BUILD_NETWORK()

    
    
    """
    In original resnet, 6n+2 layers for CIFAR-10.
    each feature map sizes: {32, 16, 8}
    # of filters: {16, 32, 64}
    """
    def _BUILD_NETWORK(self):
        with tf.variable_scope(self.name):
            # dropout (keep_prob) rate  0.7~0.5 on training, but should be 1
            # for testing
            self.training = tf.placeholder(tf.bool)
            self.seed = 777
            # input place holders
            self.X = tf.placeholder(tf.float32, [None, 784])
            x = preproc(self.X)

            # img 28x28x1 (black/white), Input Layer
            X_img = tf.reshape(x, [-1, 28, 28, 1])
            self.Y = tf.placeholder(tf.float32, [None, 10])
            
            net = X_img
            dropout_rate = 0.7
            
            #"6n+2: {3, 5, 7, 9 ... 18} (default: 3)"
            layer_n = 3

            # conv0: conv-bn-relu [-1, 28, 28, 16]
            # conv1: [-1, 28, 28, 16] * n
            # conv2: [-1, 14, 14, 32] * n
            # conv3: [-1,  7,  7, 64] * n
            # global average pooling
            # dense

            with tf.variable_scope("conv0"):
                net = tf.layers.conv2d(net, 16, [3,3], strides=1, padding='SAME', use_bias=False,
                          kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=self.seed))
                net = tf.layers.batch_normalization(net, training=self.training)
                net = tf.nn.relu(net)

            with tf.variable_scope("conv1"):
                for i in range(layer_n):
                    net = self.residual_block(net, 16, name="resblock{}".format(i+1))
                    assert net.shape[1:] == [28, 28, 16]

            with tf.variable_scope("conv2"):
                for i in range(layer_n):
                    net = self.residual_block(net, 32, downsampling=(i==0), name="resblock{}".format(i+1))
                    assert net.shape[1:] == [14, 14, 32]

            with tf.variable_scope("conv3"):
                for i in range(layer_n):
                    net = self.residual_block(net, 64, downsampling=(i==0), name="resblock{}".format(i+1))
                    assert net.shape[1:] == [7, 7, 64]

            with tf.variable_scope("fc"):
                net = tf.reduce_mean(net, [1,2]) # global average pooling
                assert net.shape[1:] == [64]

                self.Pred_m = tf.layers.dense(net, 10, kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=self.seed), name="logits")
            
            
        # define cost/loss & optimizer
        self.cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(
            logits=self.Pred_m, labels=self.Y))
        self.optimizer = tf.train.AdamOptimizer(learning_rate = Alpha_Lr).minimize(self.cost)

        correct_prediction = tf.equal(
            tf.argmax(self.Pred_m, 1), tf.argmax(self.Y, 1))
        self.accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))

    def predict(self, x_test, training=False):
        return self.sess.run(self.Pred_m,feed_dict={self.X: x_test, self.training: training})

    def get_accuracy(self, x_test, y_test, training=False):
        return self.sess.run(self.accuracy,feed_dict={self.X: x_test,self.Y: y_test, self.training: training})

    def train(self, x_data, y_data, training=True):
        return self.sess.run([self.cost, self.optimizer], feed_dict={
            self.X: x_data, self.Y: y_data, self.training: training})

# initialize
sess = tf.Session()
m1 = Model(sess, "m1")

sess.run(tf.global_variables_initializer())

start_time = time.time()
print('Learning Started!')

# train my model
for episode in range(N_EPISODES):
    avg_cost = 0    
    #total_batch = int(mnist.train.num_examples / batch_size)
    total_batch = 64
    for i in range(total_batch):
        batch_xs, batch_ys = mnist.train.next_batch(batch_size)
        c, _ = m1.train(batch_xs, batch_ys)
        avg_cost += c / total_batch

    print('episode:', '%05d' % (episode + 1), 'cost =', '{:.5f}'.format(avg_cost))
    
    elapsed_time = datetime.timedelta(seconds=int(time.time()-start_time))
    print("[{}]".format(elapsed_time))

print('Learning Finished!')

# Test model and check accuracy
print('Accuracy:', m1.get_accuracy(mnist.test.images[:512], mnist.test.labels[:512]))

elapsed_time = time.time() - start_time
formatted = datetime.timedelta(seconds=int(elapsed_time))
print("=== training time elapsed: {}s ===".format(formatted))

#########
# 결과 확인 (matplot)
######
#labels = sess.run(Pred_m,feed_dict={X: mnist.test.images,Y: mnist.test.labels,keep_prob: 1})
#labels = m1.train(feed_dict={X: mnist.test.images,Y: mnist.test.labels,keep_prob: 1})
labels = m1.predict(mnist.test.images[:512],1)
fig = plt.figure()
for i in range(60):
    subplot = fig.add_subplot(4, 15, i + 1)
    subplot.set_xticks([])
    subplot.set_yticks([])
    subplot.set_title('%d' % np.argmax(labels[i]))
    subplot.imshow(mnist.test.images[i].reshape((28, 28)),
                   cmap=plt.cm.gray_r)

plt.show()


# 세션을 닫습니다.
sess.close()


# Step 10. Tune hyperparameters:
# Step 11. Deploy/predict new outcomes:

