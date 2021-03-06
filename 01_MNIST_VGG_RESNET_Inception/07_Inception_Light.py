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

# chk: variable_scope name duplication
def conv_bn_activ_dropout(x, n_filters, kernel_size, strides, dropout_rate, training, seed, padding='SAME', activ_fn=tf.nn.relu, name="conv_bn_activ_dropout"):
    # with tf.variable_scope(name):
    net = tf.layers.conv2d(x, n_filters, kernel_size, strides=strides, padding=padding, use_bias=False,
                          kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=seed))
    net = tf.layers.batch_normalization(net, training=training)
    net = activ_fn(net)
    if dropout_rate > 0.0: # 0.0 dropout rate means no dropout
        net = tf.layers.dropout(net, rate=dropout_rate, training=training, seed=seed)

    return net

def conv_bn_activ(x, n_filters, kernel_size, strides, training, seed, padding='SAME', activ_fn=tf.nn.relu, name="conv_bn_activ"):
    return conv_bn_activ_dropout(x, n_filters, kernel_size, strides, 0.0, training, seed, padding, activ_fn, name)


class Model:
    def conv_bn_activ(self, x, n_filters, kernel_size, strides=1, padding='SAME', activ_fn=tf.nn.relu, name="conv_bn_activ"):
        return conv_bn_activ(x, n_filters, kernel_size, strides, training=self.training, seed=self.seed, padding=padding, activ_fn=activ_fn, name=name)

    def inception_block_a(self, x, name='inception_a'):
        # num of channels: 96 = 24*4
        with tf.variable_scope(name):
            # with tf.variable_scope("branch1"):
            b1 = tf.layers.average_pooling2d(x, [3,3], 1, padding='SAME')
            b1 = self.conv_bn_activ(b1, 24, [1,1])

            # with tf.variable_scope("branch2"):
            b2 = self.conv_bn_activ(x, 24, [1,1])

            # with tf.variable_scope("branch3"):
            b3 = self.conv_bn_activ(x, 16, [1,1])
            b3 = self.conv_bn_activ(b3, 24, [3,3])

            # with tf.variable_scope("branch4"):
            b4 = self.conv_bn_activ(x, 16, [1,1])
            b4 = self.conv_bn_activ(b4, 24, [3,3])
            b4 = self.conv_bn_activ(b4, 24, [3,3])

            concat = tf.concat([b1, b2, b3, b4], axis=-1) # Q. -1 axis works well?
            return concat

    def inception_block_b(self, x, name='inception_b'):
        # num of channels: 256 = 32 + 96 + 64 + 64
        with tf.variable_scope(name):
            b1 = tf.layers.average_pooling2d(x, [3,3], 1, padding='SAME')
            b1 = self.conv_bn_activ(b1, 32, [1,1])

            b2 = self.conv_bn_activ(x, 96, [1,1])

            b3 = self.conv_bn_activ(x, 48, [1,1])
            b3 = self.conv_bn_activ(b3, 56, [1,7])
            b3 = self.conv_bn_activ(b3, 64, [7,1])

            b4 = self.conv_bn_activ(x, 48, [1,1])
            b4 = self.conv_bn_activ(b4, 48, [1,7])
            b4 = self.conv_bn_activ(b4, 48, [7,1])
            b4 = self.conv_bn_activ(b4, 64, [1,7])
            b4 = self.conv_bn_activ(b4, 64, [7,1])

            return tf.concat([b1, b2, b3, b4], axis=-1)

    def inception_block_c(self, x, name='inception_c'):
        # num of channels: 384 = 64*6
        with tf.variable_scope(name):
            b1 = tf.layers.average_pooling2d(x, [3,3], 1, padding='SAME')
            b1 = self.conv_bn_activ(b1, 64, [1,1])

            b2 = self.conv_bn_activ(x, 64, [1,1])

            b3 = self.conv_bn_activ(x, 96, [1,1])
            b3_1 = self.conv_bn_activ(b3, 64, [1,3])
            b3_2 = self.conv_bn_activ(b3, 64, [3,1])

            b4 = self.conv_bn_activ(x, 96, [1,1])
            b4 = self.conv_bn_activ(b4, 112, [1,3])
            b4 = self.conv_bn_activ(b4, 128, [3,1])
            b4_1 = self.conv_bn_activ(b4, 64, [3,1])
            b4_2 = self.conv_bn_activ(b4, 64, [1,3])

            return tf.concat([b1, b2, b3_1, b3_2, b4_1, b4_2], axis=-1)

    # reduction block do downsampling & change ndim of channel
    def reduction_block_a(self, x, name='reduction_a'):
        # 96 => 256 (= 96 + 64 + 96)
        # SAME : 28 > 14 > 7 > 4
        # VALID: 28 > 13 > 6 > 3
        with tf.variable_scope(name):
            b1 = tf.layers.max_pooling2d(x, [3,3], 2, padding='SAME') # 96
            
            b2 = self.conv_bn_activ(x, 96, [3,3], strides=2)
            
            b3 = self.conv_bn_activ(x, 48, [1,1])
            b3 = self.conv_bn_activ(b3, 56, [3,3])
            b3 = self.conv_bn_activ(b3, 64, [3,3], strides=2)

            return tf.concat([b1, b2, b3], axis=-1)

    def reduction_block_b(self, x, name='reduction_b'):
        # 256 => 384 (= 256 + 48 + 80)
        with tf.variable_scope(name):
            b1 = tf.layers.max_pooling2d(x, [3,3], 2, padding='SAME') # 256
            
            b2 = self.conv_bn_activ(x, 48, [1,1])
            b2 = self.conv_bn_activ(b2, 48, [3,3], strides=2)
            
            b3 = self.conv_bn_activ(x, 64, [1,1])
            b3 = self.conv_bn_activ(b3, 64, [1,7])
            b3 = self.conv_bn_activ(b3, 80, [7,1])
            b3 = self.conv_bn_activ(b3, 80, [3,3], strides=2)

            return tf.concat([b1, b2, b3], axis=-1)

    """
    def build_inception(self, x):
        # 28 x 28 x 1
        # [28, 28, 1] => [28, 28, 96]
        with tf.variable_scope('pre_inception'):
            b1 = self.conv_bn_activ(x, 32, [1,1])
            b1 = self.conv_bn_activ(b1, 48, [3,3])

            b2 = self.conv_bn_activ(x, 32, [1,1])
            b2 = self.conv_bn_activ(b2, 32, [1,7])
            b2 = self.conv_bn_activ(b2, 32, [7,1])
            b2 = self.conv_bn_activ(b2, 48, [3,3])

            net = tf.concat([b1, b2], axis=-1)
            assert net.shape[1:] == [28, 28, 96]

        # inception A
        # [28, 28, 96]
        with tf.variable_scope("inception-A"):
            for i in range(2):
                net = self.inception_block_a(net, name="inception-block-a{}".format(i))
            assert net.shape[1:] == [28, 28, 96]

        # reduction A
        # [28, 28, 96] => [14, 14, 256]
        with tf.variable_scope("reduction-A"):
            net = self.reduction_block_a(net)
            assert net.shape[1:] == [14, 14, 256]

        # inception B
        with tf.variable_scope("inception-B"):
            for i in range(3):
                net = self.inception_block_b(net, name="inception-block-b{}".format(i))
            assert net.shape[1:] == [14, 14, 256]

        # reduction B
        # [14, 14, 256] => [7, 7, 384]
        with tf.variable_scope("reduction-B"):
            net = self.reduction_block_b(net)
            assert net.shape[1:] == [7, 7, 384]

        # inception C
        with tf.variable_scope("inception-C"):
            for i in range(1):
                net = self.inception_block_c(net, name="inception-block-c{}".format(i))
            assert net.shape[1:] == [7, 7, 384]

        # GAP(Global Average Pooling) + dense
        with tf.variable_scope("fc"):
            net = tf.reduce_mean(net, [1,2]) # GAP
            assert net.shape[1:] == [384]
            net = tf.layers.dropout(net, rate=0.2, training=self.training, seed=self.seed)
            logits = tf.layers.dense(net, 10, kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=self.seed), name="logits")

        return logits
    """
    def __init__(self, sess, name):
        self.sess = sess
        self.name = name
        self._BUILD_NETWORK()
    # |output channels| = |input channels| (inception block)
    # each inception block has fixed # of channels

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
            
            # Pre-Inception_Layer
            # 28 x 28 x 1
            # [28, 28, 1] => [28, 28, 96]
            # 28 x 28 x 1
            # [28, 28, 1] => [28, 28, 96]
            with tf.variable_scope('pre_inception'):
                b1 = self.conv_bn_activ(X_img, 32, [1,1])
                b1 = self.conv_bn_activ(b1, 48, [3,3])

                b2 = self.conv_bn_activ(X_img, 32, [1,1])
                b2 = self.conv_bn_activ(b2, 32, [1,7])
                b2 = self.conv_bn_activ(b2, 32, [7,1])
                b2 = self.conv_bn_activ(b2, 48, [3,3])

                net = tf.concat([b1, b2], axis=-1)
                assert net.shape[1:] == [28, 28, 96]
            
            # inception A-1
            # [28, 28, 96]
            
            # inception A-2
            # [28, 28, 96]
            
            # reduction A
            # [28, 28, 96] => [14, 14, 256]
            
            # inception B
            
            # reduction B
            # [14, 14, 256] => [7, 7, 384]
            
            # inception C
            
            # GAP(Global Average Pooling) + dense
            
            # Pre-Inception_Layer
            # 28 x 28 x 1
            # [28, 28, 1] => [28, 28, 96]
            # inception A-1
            # [28, 28, 96]
            # with tf.variable_scope("branch1"):
            # reduction A
            # [28, 28, 96] => [14, 14, 256]
            
            # 96 => 256 (= 96 + 64 + 96)
            # SAME : 28 > 14 > 7 > 4
            # VALID: 28 > 13 > 6 > 3
            # inception B
            
            # reduction B
            # [14, 14, 256] => [7, 7, 384]
            
            # inception C
            
            # GAP(Global Average Pooling) + dense

            # inception A
            # [28, 28, 96]
            with tf.variable_scope("inception-A"):
                for i in range(2):
                    net = self.inception_block_a(net, name="inception-block-a{}".format(i))
                assert net.shape[1:] == [28, 28, 96]

            # reduction A
            # [28, 28, 96] => [14, 14, 256]
            with tf.variable_scope("reduction-A"):
                net = self.reduction_block_a(net)
                assert net.shape[1:] == [14, 14, 256]

            # inception B
            with tf.variable_scope("inception-B"):
                for i in range(3):
                    net = self.inception_block_b(net, name="inception-block-b{}".format(i))
                assert net.shape[1:] == [14, 14, 256]

            # reduction B
            # [14, 14, 256] => [7, 7, 384]
            with tf.variable_scope("reduction-B"):
                net = self.reduction_block_b(net)
                assert net.shape[1:] == [7, 7, 384]

            # inception C
            with tf.variable_scope("inception-C"):
                for i in range(1):
                    net = self.inception_block_c(net, name="inception-block-c{}".format(i))
                assert net.shape[1:] == [7, 7, 384]

            # GAP(Global Average Pooling) + dense
            with tf.variable_scope("fc"):
                net = tf.reduce_mean(net, [1,2]) # GAP
                assert net.shape[1:] == [384]
                net = tf.layers.dropout(net, rate=0.7, training=self.training, seed=self.seed)
                
            self.logits = tf.layers.dense(inputs=net, units=10)
            """
            logits = tf.layers.dense(net, 10, kernel_initializer=tf.contrib.layers.variance_scaling_initializer(seed=self.seed), name="logits")

            # Dense Layer with Relu
            # flat = tf.reshape(DROP_OUT_03, [-1, 128 * 4 * 4])
            
            flat = tf.contrib.layers.flatten(net)
            dense4 = tf.layers.dense(inputs=flat,
                                     units= 512, activation=tf.nn.relu)
            DROP_OUT_04 = tf.layers.dropout(inputs=dense4,
                                         rate=0.7, training=self.training)
            """
            # Pred_m (no activation) Layer: L5 Final FC 625 inputs -> 10 outputs
           

        # define cost/loss & optimizer
        self.cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(
            logits=self.logits, labels=self.Y))
        self.optimizer = tf.train.AdamOptimizer(learning_rate = Alpha_Lr).minimize(self.cost)
        self.pred = tf.argmax(self.logits, axis=1, name="prediction")
        self.accuracy = tf.reduce_mean(tf.cast(tf.equal(self.pred, tf.argmax(self.Y, axis=1)), tf.float32), name="accuracy")

    def predict(self, x_test, training=False):
        return self.sess.run(self.logits,feed_dict={self.X: x_test, self.training: training})

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

